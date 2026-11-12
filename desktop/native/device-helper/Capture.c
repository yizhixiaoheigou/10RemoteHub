/* One fixed-receiver collector: raw HID reports and encoded voice, no decoding,
 * keyboard injection, shell, file paths or arbitrary USB commands from clients.
 * Spawned only by the authenticated root service. stdin: S=start T=stop X=exit. */
#include <libusb.h>
#include <fcntl.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t stopping;
static double clock_now(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}
static void interrupted(int signal_number) { (void)signal_number; stopping = 1; }
static void error(const char *operation, int code) {
    printf("{\"type\":\"error\",\"message\":\"collector %s: %s (%d)\"}\n",
           operation, libusb_error_name(code), code);
}
static void trace(const char *event, int phase, int code) {
    printf("{\"type\":\"debug\",\"event\":\"%s\",\"phase\":%d,\"code\":%d}\n", event, phase, code);
}
static void trace_bytes(const char *event, int phase, const unsigned char *bytes) {
    printf("{\"type\":\"debug\",\"event\":\"%s\",\"phase\":%d,\"code\":0,\"hex\":\"%02x%02x%02x%02x\"}\n",
           event, phase, bytes[0], bytes[1], bytes[2], bytes[3]);
}
static void packet(const char *type, int interface, const unsigned char *bytes, int length) {
    printf("{\"type\":\"%s\",\"interface\":%d,\"hex\":\"", type, interface);
    for (int i = 0; i < length; ++i) printf("%02x", bytes[i]);
    puts("\"}");
}
static int command(libusb_device_handle *handle, int code, int arg1, int arg2) {
    unsigned char bytes[64] = {1, (unsigned char)code, (unsigned char)arg1, (unsigned char)arg2};
    int transferred = 0;
    int rc = libusb_bulk_transfer(handle, 0x05, bytes, sizeof bytes, &transferred, 1000);
    trace_bytes("voice_command", 0, bytes);
    return rc ? rc : transferred == 64 ? 0 : LIBUSB_ERROR_IO;
}
typedef struct {
    unsigned char endpoint, type, interface;
    uint16_t size;
    struct libusb_transfer *transfer;
    unsigned char buffer[64];
    int active, completed;
    double retry_after;
} Reader;

static void received(struct libusb_transfer *transfer) {
    Reader *reader = transfer->user_data;
    reader->active = 0;
    reader->completed = 1;
}

static int submit_reader(Reader *reader) {
    reader->completed = 0;
    int rc = libusb_submit_transfer(reader->transfer);
    if (!rc) reader->active = 1;
    return rc;
}

static int transfer_error(enum libusb_transfer_status status) {
    switch (status) {
        case LIBUSB_TRANSFER_COMPLETED: return 0;
        case LIBUSB_TRANSFER_TIMED_OUT: return 0; // preserve any received bytes
        case LIBUSB_TRANSFER_NO_DEVICE: return LIBUSB_ERROR_NO_DEVICE;
        case LIBUSB_TRANSFER_STALL: return LIBUSB_ERROR_PIPE;
        case LIBUSB_TRANSFER_OVERFLOW: return LIBUSB_ERROR_OVERFLOW;
        default: return LIBUSB_ERROR_IO;
    }
}

static void stop_readers(libusb_context *context, Reader *readers, int count) {
    for (int i = 0; i < count; ++i)
        if (readers[i].active) libusb_cancel_transfer(readers[i].transfer);
    double deadline = clock_now() + 2;
    for (;;) {
        int active = 0;
        for (int i = 0; i < count; ++i) active += readers[i].active;
        if (!active) break;
        // Never free a transfer before its cancellation callback has completed.
        if (clock_now() > deadline) {
            error("cancel reads; unplug receiver", LIBUSB_ERROR_TIMEOUT);
            _exit(1);
        }
        struct timeval wait = {0, 20000};
        libusb_handle_events_timeout(context, &wait);
    }
    for (int i = 0; i < count; ++i)
        if (readers[i].transfer) libusb_free_transfer(readers[i].transfer);
}

static int report_length(const struct libusb_interface_descriptor *interface) {
    const unsigned char *extra = interface->extra;
    int remaining = interface->extra_length;
    while (remaining >= 2) {
        int length = extra[0];
        if (length < 2 || length > remaining) return -1;
        if (extra[1] == 0x21) { // HID descriptor: count, then type/u16-length entries
            if (length < 6 || 6 + 3 * extra[5] > length) return -1;
            for (int i = 0; i < extra[5]; ++i) {
                const unsigned char *entry = extra + 6 + 3*i;
                if (entry[0] == 0x22) {
                    int size = entry[1] | (entry[2] << 8);
                    return size > 0 && size <= 1024 ? size : -1;
                }
            }
            return -1;
        }
        extra += length; remaining -= length;
    }
    return -1;
}

int main(int argc, char **argv) {
    (void)argv;
    pid_t parent = getppid();
    if (argc != 1 || geteuid() != 0 || parent <= 1) return 78;
    signal(SIGTERM, interrupted); signal(SIGINT, interrupted);
    signal(SIGPIPE, SIG_IGN); setbuf(stdout, NULL);
    if (fcntl(STDIN_FILENO, F_SETFL, O_NONBLOCK) < 0) return 78;
    libusb_context *context = NULL;
    libusb_device_handle *handle = NULL;
    struct libusb_config_descriptor *config = NULL;
    int detached = 0, claimed[5] = {0}, phase = 0, rc = libusb_init(&context);
    const char *operation = "initialize";
    Reader readers[8] = {0}; int reader_count = 0, seen[5] = {0}, voice_in = 0, voice_out = 0;
    int report_lengths[5] = {0};
    char descriptor_operation[80];
    double deadline = 0, keepalive = 0;
    if (rc) { error(operation, rc); return 1; }
    handle = libusb_open_device_with_vid_pid(context, 0x0416, 0x0602);
    operation = "open receiver";
    if (!handle) { rc = LIBUSB_ERROR_NO_DEVICE; goto cleanup; }
    operation = "read configuration";
    rc = libusb_get_active_config_descriptor(libusb_get_device(handle), &config);
    if (rc) goto cleanup;
    operation = "validate configuration";
    rc = LIBUSB_ERROR_NOT_SUPPORTED;
    if (config->bNumInterfaces != 5) goto cleanup;
    for (int i = 0; i < config->bNumInterfaces; ++i) {
        const struct libusb_interface *group = &config->interface[i];
        for (int a = 0; a < group->num_altsetting; ++a) {
            const struct libusb_interface_descriptor *iface = &group->altsetting[a];
            if (iface->bAlternateSetting) continue;
            int number = iface->bInterfaceNumber;
            if (number > 4 || seen[number] || iface->bInterfaceClass != 3) goto cleanup;
            seen[number] = 1;
            report_lengths[number] = report_length(iface);
            if (report_lengths[number] < 0) goto cleanup;
            for (int e = 0; e < iface->bNumEndpoints; ++e) {
                const struct libusb_endpoint_descriptor *ep = &iface->endpoint[e];
                int type = ep->bmAttributes & 3;
                if (number == 3 && ep->bEndpointAddress == 0x84 && type == 3 && ep->wMaxPacketSize == 64) voice_in = 1;
                if (number == 3 && ep->bEndpointAddress == 0x05 && type == 2 && ep->wMaxPacketSize == 64) voice_out = 1;
                if (!(ep->bEndpointAddress & 0x80)) continue;
                if (reader_count >= 8 || (type != 2 && type != 3) || !ep->wMaxPacketSize || ep->wMaxPacketSize > 64) goto cleanup;
                readers[reader_count++] = (Reader){.endpoint = ep->bEndpointAddress,
                    .type = type, .interface = number, .size = ep->wMaxPacketSize};
            }
        }
    }
    if (!voice_in || !voice_out || !seen[0] || !seen[1] || !seen[2] || !seen[3] || !seen[4]) goto cleanup;
    operation = "capture receiver";
    // macOS captures the entire device once, including all HID interfaces.
    rc = libusb_detach_kernel_driver(handle, 3);
    if (rc) goto cleanup;
    detached = 1;
    for (int number = 0; number < 5; ++number) {
        if (stopping || getppid() != parent) { rc = 0; goto cleanup; }
        operation = "claim interface";
        rc = libusb_claim_interface(handle, number);
        if (rc) goto cleanup;
        claimed[number] = 1;
        unsigned char descriptor[1024];
        snprintf(descriptor_operation, sizeof descriptor_operation,
                 "read HID descriptor interface %d length %d", number, report_lengths[number]);
        operation = descriptor_operation;
        rc = libusb_control_transfer(handle, 0x81, 6, 0x2200, number, descriptor,
                                     (uint16_t)report_lengths[number], 1000);
        if (rc != report_lengths[number]) { if (rc >= 0) rc = LIBUSB_ERROR_IO; goto cleanup; }
        packet("descriptor", number, descriptor, rc);
    }
    // Keep every IN endpoint armed concurrently. Periodic synchronous timeouts
    // abort the pipe on macOS and can lose the following key-release report.
    operation = "start continuous reads";
    for (int i = 0; i < reader_count; ++i) {
        Reader *r = &readers[i];
        r->transfer = libusb_alloc_transfer(0);
        if (!r->transfer) { rc = LIBUSB_ERROR_NO_MEM; goto cleanup; }
        if (r->type == 3)
            libusb_fill_interrupt_transfer(r->transfer, handle, r->endpoint, r->buffer, r->size, received, r, 0);
        else
            libusb_fill_bulk_transfer(r->transfer, handle, r->endpoint, r->buffer, r->size, received, r, 0);
        rc = submit_reader(r);
        if (rc) goto cleanup;
    }
    operation = "initial voice sync";
    rc = command(handle, 8, 1, 0);
    if (rc) goto cleanup;
    trace("collector_ready_sync", 0, 0);
    puts("{\"type\":\"ready\",\"interfaces\":4,\"audio\":true}");
    while (!stopping && getppid() == parent) {
        char controls[64];
        ssize_t length = read(STDIN_FILENO, controls, sizeof controls);
        if (!length) break; // daemon exited or closed the control pipe
        for (ssize_t i = 0; i < length; ++i) {
            operation = "voice command";
            if (controls[i] == 'S' && phase == 0) {
                trace("control_start", phase, 0);
                rc = command(handle, 0x82, 1, 0);
                if (!rc) rc = command(handle, 8, 1, 0);
                if (rc) goto cleanup;
                phase = 1; deadline = clock_now() + 8;
            } else if (controls[i] == 'T' && phase) {
                trace("control_stop", phase, 0);
                if (phase != 4) {
                    rc = command(handle, 1, 0, 0);
                    if (rc) goto cleanup;
                }
                // Briefly drain tail packets before ending the recognition key.
                if (phase == 3) { phase = 4; deadline = clock_now() + 0.06; }
                else { phase = 0; puts("{\"type\":\"end\"}"); }
            } else if (controls[i] == 'X') { stopping = 1; break; }
        }
        if (stopping) break;
        struct timeval wait = {0, 20000};
        operation = "wait for receiver";
        rc = libusb_handle_events_timeout(context, &wait);
        if (rc == LIBUSB_ERROR_INTERRUPTED) { rc = 0; continue; }
        if (rc) goto cleanup;
        for (int i = 0; i < reader_count; ++i) {
            Reader *r = &readers[i];
            if (!r->completed) continue;
            unsigned char bytes[64];
            int transferred = r->transfer->actual_length;
            operation = "read receiver";
            enum libusb_transfer_status status = r->transfer->status;
            if (!stopping && (status == LIBUSB_TRANSFER_ERROR || status == LIBUSB_TRANSFER_CANCELLED)) {
                double now = clock_now();
                if (now < r->retry_after) { rc = 0; continue; }
                r->retry_after = now + 0.1;
                trace("read_retry", phase, status);
                rc = submit_reader(r);
                if (!rc) { rc = 0; continue; }
            }
            rc = transfer_error(status);
            if (rc) goto cleanup;
            r->retry_after = 0;
            if (transferred < 0 || transferred > r->size) { rc = LIBUSB_ERROR_IO; goto cleanup; }
            memcpy(bytes, r->buffer, (size_t)transferred);
            // Re-arm before processing or sending any voice control command.
            rc = submit_reader(r);
            if (rc) goto cleanup;
            if (!transferred) continue;
            if (r->interface != 3) { packet("report", r->interface, bytes, transferred); continue; }
            operation = "voice handshake";
            if (transferred >= 2 && bytes[0] == 1 && bytes[1] != 0x81) {
                memset(bytes + transferred, 0, (size_t)(64 - transferred));
                trace_bytes("voice_packet", phase, bytes);
            }
            if (phase == 0 && transferred >= 3 && !memcmp(bytes, "\x01\x82\x03", 3)) {
                trace("vendor_request", phase, 0);
                rc = command(handle, 0x82, 1, 0);
                if (!rc) rc = command(handle, 8, 1, 0);
                if (rc) goto cleanup;
                phase = 1; deadline = clock_now() + 8;
            } else if (phase == 1 && transferred >= 4 && !memcmp(bytes, "\x01\x08\x01\x00", 4)) {
                rc = command(handle, 1, 1, 0);
                if (rc) goto cleanup;
                phase = 2;
            } else if (phase == 2 && transferred >= 4 && !memcmp(bytes, "\x01\x01\x01\x00", 4)) {
                trace("audio_started", phase, 0);
                phase = 3; deadline = clock_now() + 60; keepalive = 0;
                puts("{\"type\":\"start\"}");
            } else if (transferred >= 3 && bytes[0] == 1 && bytes[1] == 0x86) {
                trace("voice_state", phase, bytes[2]);
                if (!bytes[2] && phase && phase != 4) {
                    // The receiver can end a long take itself. Stop keepalives
                    // now; a later HID release is not a USB disconnect.
                    trace("voice_remote_end", phase, bytes[3]);
                    rc = command(handle, 1, 0, 0);
                    if (rc) goto cleanup;
                    if (phase == 3) { phase = 4; deadline = clock_now() + 0.06; }
                    else { phase = 0; puts("{\"type\":\"end\"}"); }
                }
            } else if ((phase == 3 || phase == 4) && transferred >= 2 && bytes[0] == 1 && bytes[1] == 0x81) {
                if (transferred != 64) { rc = LIBUSB_ERROR_IO; goto cleanup; }
                packet("audio", 3, bytes, transferred);
            }
        }
        double now = clock_now();
        operation = "voice keepalive";
        if (phase == 3 && now >= keepalive) {
            rc = command(handle, 10, 84, 69);
            if (rc) goto cleanup;
            keepalive = now + 1;
        }
        if (phase && now >= deadline) {
            if (phase != 4) {
                operation = "voice stop";
                trace("voice_timeout", phase, 0);
                rc = command(handle, 1, 0, 0);
                if (rc) goto cleanup;
            }
            if (phase < 3) puts("{\"type\":\"warning\",\"message\":\"voice handshake timeout\"}");
            phase = 0; puts("{\"type\":\"end\"}");
        }
        if (ferror(stdout)) break;
    }
cleanup:
    trace("collector_exit", phase, rc);
    if (rc) error(operation, rc);
    if (handle && phase) {
        command(handle, 1, 0, 0); puts("{\"type\":\"end\"}");
    }
    stop_readers(context, readers, reader_count);
    for (int number = 4; number >= 0; --number)
        if (claimed[number]) libusb_release_interface(handle, number);
    if (detached) {
        int restored = libusb_attach_kernel_driver(handle, 3);
        if (restored) { error("restore drivers; unplug receiver", restored); rc = restored; }
    }
    if (config) libusb_free_config_descriptor(config);
    if (handle) libusb_close(handle);
    libusb_exit(context);
    return rc ? 1 : 0;
}
