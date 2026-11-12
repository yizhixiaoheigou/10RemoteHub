/* Deterministic USB fixture. No link to libusb, root, launchd or real hardware. */
#include <libusb.h>
#include <assert.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
static int scenario, stage, reads, detached, restored, claims, releases, stops, audio, key_reports, remote_ended;
static int ready_syncs, vendor_sent;
static double ticks;
static struct libusb_transfer *pending_transfers[16];
static int cancel_requested[16], allocations, freed, submitted, cancelled;
static uid_t fixture_uid(void) { return 0; }
static pid_t fixture_parent(void) { return reads > 15 ? 1 : 42; }
static int fixture_fcntl(int fd, int cmd, ...) { (void)fd; (void)cmd; return 0; }
static int fixture_clock(clockid_t kind, struct timespec *t) {
    (void)kind; ticks += scenario == 7 ? 0.3 : scenario == 18 && stage == 3 ? 61 : 0.02;
    t->tv_sec = (time_t)ticks; t->tv_nsec = (long)((ticks - t->tv_sec)*1e9); return 0;
}
static ssize_t fixture_read(int fd, void *buffer, size_t size) {
    (void)fd; (void)size; reads++;
    if (reads == 1 && scenario != 14 && scenario != 15) { *(char *)buffer = 'S'; return 1; }
    if ((scenario == 3 || scenario == 15) && reads == 2) { *(char *)buffer = 'T'; return 1; }
    if (audio && reads == 5 && scenario < 16) { *(char *)buffer = 'T'; return 1; }
    return -1;
}
#define main collector_main
#define geteuid fixture_uid
#define getppid fixture_parent
#define fcntl fixture_fcntl
#define clock_gettime fixture_clock
#define read fixture_read
#include "../device-helper/Capture.c"
#undef main
#undef read
#undef fcntl
#undef getppid
#undef geteuid
#undef clock_gettime

static unsigned char hid_descriptor[9] = {9, 0x21, 0x11, 1, 0, 1, 0x22, 2, 0};
static struct libusb_endpoint_descriptor endpoints[6];
static struct libusb_interface_descriptor interfaces[5];
static struct libusb_interface groups[5];
static struct libusb_config_descriptor configuration;
int libusb_init(libusb_context **ctx) { *ctx = (void *)1; return 0; }
void libusb_exit(libusb_context *ctx) { (void)ctx; }
libusb_device_handle *libusb_open_device_with_vid_pid(libusb_context *ctx, uint16_t v, uint16_t p) {
    (void)ctx; assert(v == 0x0416 && p == 0x0602); return (void *)2;
}
libusb_device *libusb_get_device(libusb_device_handle *h) { (void)h; return (void *)3; }
void libusb_close(libusb_device_handle *h) { (void)h; }
int libusb_get_active_config_descriptor(libusb_device *d, struct libusb_config_descriptor **out) {
    (void)d;
    if (scenario == 4) hid_descriptor[7] = 0; // reject zero report length before capture
    for (int i = 0; i < 5; ++i) {
        endpoints[i].bEndpointAddress = i == 3 ? 0x84 : 0x81 + i;
        endpoints[i].bmAttributes = 3; endpoints[i].wMaxPacketSize = i == 3 ? 64 : 8;
        interfaces[i].bInterfaceNumber = i; interfaces[i].bInterfaceClass = 3;
        interfaces[i].extra = hid_descriptor; interfaces[i].extra_length = sizeof hid_descriptor;
        interfaces[i].bNumEndpoints = 1; interfaces[i].endpoint = &endpoints[i];
        groups[i].num_altsetting = 1; groups[i].altsetting = &interfaces[i];
    }
    // Voice IN + OUT must be contiguous.
    endpoints[5] = endpoints[4]; interfaces[4].endpoint = &endpoints[5];
    endpoints[4].bEndpointAddress = 0x05; endpoints[4].bmAttributes = 2; endpoints[4].wMaxPacketSize = 64;
    interfaces[3].bNumEndpoints = 2;
    configuration.bNumInterfaces = scenario == 1 ? 4 : 5; configuration.interface = groups;
    *out = &configuration; return 0;
}
void libusb_free_config_descriptor(struct libusb_config_descriptor *c) { (void)c; }
int libusb_detach_kernel_driver(libusb_device_handle *h, int n) { (void)h; assert(n == 3); detached++; return 0; }
int libusb_attach_kernel_driver(libusb_device_handle *h, int n) { (void)h; assert(n == 3); restored++; return 0; }
int libusb_claim_interface(libusb_device_handle *h, int n) {
    (void)h; if (scenario == 2 && n == 2) return LIBUSB_ERROR_ACCESS; claims++; return 0;
}
int libusb_release_interface(libusb_device_handle *h, int n) {
    (void)h; (void)n;
    for (int i = 0; i < 16; ++i) assert(!pending_transfers[i]);
    releases++; return 0;
}
int libusb_control_transfer(libusb_device_handle *h, uint8_t type, uint8_t request,
                           uint16_t value, uint16_t index, unsigned char *data, uint16_t len, unsigned int timeout) {
    (void)h; (void)index; (void)timeout; assert(type == 0x81 && request == 6 && value == 0x2200 && len >= 2);
    if (len != 2) return LIBUSB_ERROR_PIPE; // hardware rejects oversized report requests
    if (scenario == 5) return 1; // never publish a truncated descriptor as ready
    data[0] = 5; data[1] = 7; return 2;
}
int libusb_bulk_transfer(libusb_device_handle *h, unsigned char ep, unsigned char *data, int len, int *count, unsigned int timeout) {
    (void)h; (void)timeout; assert(ep == 5 && len == 64);
    if (data[1] == 8) { if (!stage) ready_syncs++; stage = 1; }
    if (data[1] == 1 && data[2]) stage = 2;
    if (data[1] == 1 && !data[2]) { stage = 0; stops++; }
    *count = 64; return 0;
}
struct libusb_transfer *libusb_alloc_transfer(int packets) {
    assert(packets == 0); allocations++;
    return calloc(1, sizeof(struct libusb_transfer));
}
void libusb_free_transfer(struct libusb_transfer *transfer) {
    for (int i = 0; i < 16; ++i) assert(pending_transfers[i] != transfer);
    freed++; free(transfer);
}
int libusb_submit_transfer(struct libusb_transfer *transfer) {
    assert(transfer->timeout == 0); // no periodic pipe cancellation while holding a key
    submitted++;
    if ((scenario == 8 && submitted == 3) || (scenario == 10 && submitted == 6)) return LIBUSB_ERROR_IO;
    for (int i = 0; i < 16; ++i) {
        assert(pending_transfers[i] != transfer);
    }
    for (int i = 0; i < 16; ++i) if (!pending_transfers[i]) {
        pending_transfers[i] = transfer; cancel_requested[i] = 0; return 0;
    }
    assert(0); return LIBUSB_ERROR_NO_MEM;
}
int libusb_cancel_transfer(struct libusb_transfer *transfer) {
    for (int i = 0; i < 16; ++i) if (pending_transfers[i] == transfer) {
        cancel_requested[i] = 1; cancelled++; return 0;
    }
    return LIBUSB_ERROR_NOT_FOUND;
}
int libusb_handle_events_timeout(libusb_context *ctx, struct timeval *wait) {
    (void)ctx; assert(wait->tv_sec == 0 && wait->tv_usec <= 20000);
    int pending_count = 0;
    for (int i = 0; i < 16; ++i) pending_count += pending_transfers[i] != NULL;
    if (!cancelled) assert(pending_count >= 4); // one completed read may await re-arming
    for (int i = 0; i < 16; ++i) {
        struct libusb_transfer *t = pending_transfers[i];
        if (!t) continue;
        unsigned char *data = t->buffer;
        int length = 0;
        t->status = LIBUSB_TRANSFER_COMPLETED;
        if (cancel_requested[i]) t->status = LIBUSB_TRANSFER_CANCELLED;
        else if (scenario == 12 && t->endpoint == 0x81) t->status = LIBUSB_TRANSFER_ERROR;
        else if (scenario == 11 && t->endpoint == 0x81 && key_reports < 2) {
            t->status = LIBUSB_TRANSFER_ERROR; key_reports++;
        }
        else if (scenario == 9 && t->endpoint == 0x81) t->status = LIBUSB_TRANSFER_NO_DEVICE;
        else if ((scenario == 6 || scenario == 10) && t->endpoint == 0x81 && key_reports < 4) {
            memset(data, 0, 8); length = 8;
            if (key_reports % 2 == 0) data[2] = 30;
            key_reports++;
            if (key_reports == 2) t->status = LIBUSB_TRANSFER_TIMED_OUT;
        } else if (scenario == 7 && t->endpoint == 0x81 &&
                   (reads == 1 || reads == 12 || reads == 13 || reads == 14)) {
            memset(data, 0, 8); length = 8;
            if (reads == 1 || reads == 13) data[2] = 30;
        } else if ((scenario == 14 || (scenario == 15 && reads == 1)) && t->endpoint == 0x84 && !vendor_sent) {
            memset(data, 0, 64); data[0] = 1; data[1] = 0x82; data[2] = 3; length = 3; stage = 1; vendor_sent = 1;
        } else if ((scenario == 16 || scenario == 17) && t->endpoint == 0x84 && audio == 1 && !remote_ended) {
            memset(data, 0, 64); data[0] = 1; data[1] = 0x86; data[3] = 0x13; length = 4; remote_ended = 1;
        } else if (t->endpoint == 0x84 && stage && !(scenario == 3 && stage == 1)) {
            memset(data, 0, 64); data[0] = 1;
            if (stage == 1) { data[1] = 8; data[2] = 1; length = 4; }
            else if (stage == 2) { data[1] = 1; data[2] = 1; length = 4; stage = 3; }
            else { data[1] = 0x81; length = 64; audio++; }
        } else continue; // a pending read stays armed when no bytes arrive
        t->actual_length = length;
        pending_transfers[i] = NULL;
        t->callback(t);
    }
    return 0;
}
const char *libusb_error_name(int code) { (void)code; return "fixture-error"; }
int main(int argc, char **argv) {
    scenario = argc > 1 ? atoi(argv[1]) : 0;
    int rc = collector_main(1, argv);
    if (scenario == 1 || scenario == 4) { assert(rc && !detached && !claims); }
    else if (scenario == 2) { assert(rc && claims == 2 && releases == 2 && restored == 1); }
    else if (scenario == 5) { assert(rc && claims == 1 && releases == 1 && restored == 1); }
    else if (scenario == 8 || scenario == 9 || scenario == 10) {
        assert(rc && claims == 5 && releases == 5 && restored == 1);
    }
    else { assert(!rc && detached == 1 && claims == 5 && releases == 5 && restored == 1 && (scenario == 11 || stops > 0)); }
    assert(freed == allocations);
    for (int i = 0; i < 16; ++i) assert(!pending_transfers[i]);
    if (scenario == 8) assert(cancelled == 2);
    if (scenario == 7) assert(cancelled == 5);
    if (scenario == 0) assert(audio > 0);
    if (scenario == 16 || scenario == 17) assert(audio == 1 && stops == 1);
    if (scenario == 18) assert(!audio && stops == 1);
    if (detached && claims == 5 && !rc) assert(ready_syncs == 1);
    if (scenario == 3) assert(!audio);
    return 0;
}
