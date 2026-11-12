/* Load a HAL bundle in an isolated test host, never in the system audio service.
 * --system only enumerates the real CoreAudio device list. No recording, audio
 * playback, service restart, installation or system-default changes. */
#include <CoreAudio/AudioServerPlugIn.h>
#include <CoreAudio/AudioHardware.h>
#include <CoreFoundation/CFPlugInCOM.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "../loopback.h"

#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #x); return 1; } } while (0)
static OSStatus no_storage(AudioServerPlugInHostRef h, CFStringRef key, CFPropertyListRef *out) {
    (void)h; (void)key; *out = NULL; return 0;
}
static const AudioServerPlugInHostInterface host = {.CopyFromStorage = no_storage};

static OSStatus get(AudioServerPlugInDriverRef d, AudioObjectID obj,
                    AudioObjectPropertySelector selector, AudioObjectPropertyScope scope,
                    UInt32 size, void *out) {
    AudioObjectPropertyAddress a = {selector, scope, kAudioObjectPropertyElementMain};
    UInt32 actual = 0;
    OSStatus e = (*d)->GetPropertyData(d, obj, 0, &a, 0, NULL, size, &actual, out);
    return e ? e : (actual == size ? 0 : kAudioHardwareBadPropertySizeError);
}

static int system_devices(void) {
    AudioObjectPropertyAddress a = {kAudioHardwarePropertyDevices,
        kAudioObjectPropertyScopeGlobal, kAudioObjectPropertyElementMain};
    UInt32 size = 0;
    CHECK(AudioObjectGetPropertyDataSize(kAudioObjectSystemObject, &a, 0, NULL, &size) == 0);
    AudioDeviceID *devices = calloc(1, size);
    CHECK(devices != NULL);
    CHECK(AudioObjectGetPropertyData(kAudioObjectSystemObject, &a, 0, NULL, &size, devices) == 0);
    int found = 0;
    for (UInt32 i = 0; i < size / sizeof(*devices); ++i) {
        CFStringRef uid = NULL;
        UInt32 n = sizeof(uid);
        a.mSelector = kAudioDevicePropertyDeviceUID;
        if (AudioObjectGetPropertyData(devices[i], &a, 0, NULL, &n, &uid) != 0 || !uid) continue;
        if (CFEqual(uid, CFSTR("RemoteHubAudioDevice_UID"))) {
            printf("system_device_id=%u\n", (unsigned)devices[i]);
            for (int input = 0; input < 2; ++input) {
                a.mSelector = kAudioDevicePropertyStreamConfiguration;
                a.mScope = input ? kAudioObjectPropertyScopeInput : kAudioObjectPropertyScopeOutput;
                CHECK(AudioObjectGetPropertyDataSize(devices[i], &a, 0, NULL, &n) == 0);
                AudioBufferList *buffers = calloc(1, n);
                CHECK(buffers != NULL);
                CHECK(AudioObjectGetPropertyData(devices[i], &a, 0, NULL, &n, buffers) == 0);
                UInt32 channels = 0;
                for (UInt32 j = 0; j < buffers->mNumberBuffers; ++j) channels += buffers->mBuffers[j].mNumberChannels;
                printf("system_%s_channels=%u\n", input ? "input" : "output", (unsigned)channels);
                free(buffers);
                CHECK(channels == 2);
                a.mSelector = kAudioDevicePropertyDataSources;
                if (AudioObjectHasProperty(devices[i], &a)) {
                    CHECK(AudioObjectGetPropertyDataSize(devices[i], &a, 0, NULL, &n) == 0);
                    CHECK(n <= sizeof(UInt32)); /* No sample selectors masquerading as microphones. */
                }
            }
            a.mScope = kAudioObjectPropertyScopeGlobal;
            found = 1;
        }
        CFRelease(uid);
    }
    free(devices);
    puts(found ? "SYSTEM_REGISTERED" : "SYSTEM_NOT_REGISTERED");
    return found ? 0 : 3;
}

int main(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1], "--system")) {
        alarm(3); /* Bound queries while the audio server is restarting. */
        return system_devices();
    }
    CHECK(argc == 2);
    CFURLRef url = CFURLCreateFromFileSystemRepresentation(NULL, (const UInt8 *)argv[1], strlen(argv[1]), true);
    CHECK(url != NULL);
    CFPlugInRef plugin = CFPlugInCreate(NULL, url);
    CHECK(plugin != NULL);
    CFArrayRef factories = CFPlugInFindFactoriesForPlugInTypeInPlugIn(kAudioServerPlugInTypeUUID, plugin);
    CHECK(factories && CFArrayGetCount(factories) == 1);
    IUnknownVTbl **unknown = CFPlugInInstanceCreate(NULL, CFArrayGetValueAtIndex(factories, 0), kAudioServerPlugInTypeUUID);
    CHECK(unknown != NULL);
    AudioServerPlugInDriverRef d = NULL;
    CHECK((*unknown)->QueryInterface(unknown, CFUUIDGetUUIDBytes(kAudioServerPlugInDriverInterfaceUUID), (LPVOID *)&d) == 0);
    CHECK(d != NULL && (*d)->Initialize(d, &host) == 0);
    AudioObjectID device = 0;
    CHECK(get(d, kAudioObjectPlugInObject, kAudioPlugInPropertyDeviceList,
              kAudioObjectPropertyScopeGlobal, sizeof(device), &device) == 0);
    CFStringRef name = NULL;
    CHECK(get(d, device, kAudioObjectPropertyName, kAudioObjectPropertyScopeGlobal, sizeof(name), &name) == 0);
    char text[256];
    CHECK(CFStringGetCString(name, text, sizeof(text), kCFStringEncodingUTF8));
    printf("isolated_device_name=%s\n", text);
    CFRelease(name);
    UInt32 hidden = 1;
    CHECK(get(d, device, kAudioDevicePropertyIsHidden, kAudioObjectPropertyScopeGlobal, sizeof(hidden), &hidden) == 0);
    CHECK(hidden == 0);
    AudioObjectPropertyAddress controls = {kAudioObjectPropertyControlList,
        kAudioObjectPropertyScopeGlobal, kAudioObjectPropertyElementMain};
    UInt32 controls_size = 0;
    CHECK((*d)->GetPropertyDataSize(d, device, 0, &controls, 0, NULL, &controls_size) == 0);
    CHECK(controls_size == 0); /* Sample volume/mute/data-source controls do nothing. */
    AudioObjectID streams[2];
    for (int input = 0; input < 2; ++input) {
        CHECK(get(d, device, kAudioDevicePropertyStreams,
                  input ? kAudioObjectPropertyScopeInput : kAudioObjectPropertyScopeOutput,
                  sizeof(streams[input]), &streams[input]) == 0);
        AudioStreamBasicDescription format = {0};
        CHECK(get(d, streams[input], kAudioStreamPropertyVirtualFormat, kAudioObjectPropertyScopeGlobal,
                  sizeof(format), &format) == 0);
        CHECK(format.mSampleRate == 48000 && format.mChannelsPerFrame == 2 && format.mBitsPerChannel == 32);
        CHECK(format.mFormatID == kAudioFormatLinearPCM && (format.mFormatFlags & kAudioFormatFlagIsFloat));
        printf("isolated_%s=48000Hz/2ch/float32\n", input ? "input" : "output");
    }
    AudioObjectID owned[2] = {0};
    CHECK(get(d, device, kAudioObjectPropertyOwnedObjects, kAudioObjectPropertyScopeGlobal,
              sizeof(owned), owned) == 0);
    CHECK(owned[0] == streams[1] && owned[1] == streams[0]);
    CHECK((*d)->StartIO(d, device, 1) == 0);
    float samples[128], received[128];
    for (unsigned i = 0; i < 128; ++i) samples[i] = (float)i / 256.0f;
    memset(received, 0, sizeof(received));
    AudioServerPlugInIOCycleInfo cycle = {0};
    cycle.mOutputTime.mSampleTime = 4096;
    cycle.mInputTime.mSampleTime = 4096 + RH_LOOPBACK_DELAY;
    CHECK((*d)->DoIOOperation(d, device, streams[0], 1, kAudioServerPlugInIOOperationWriteMix, 64, &cycle, samples, NULL) == 0);
    CHECK((*d)->DoIOOperation(d, device, streams[1], 1, kAudioServerPlugInIOOperationReadInput, 64, &cycle, received, NULL) == 0);
    CHECK(memcmp(samples, received, sizeof(samples)) == 0);
    CHECK((*d)->StopIO(d, device, 1) == 0);
    puts("ISOLATED_PLUGIN_PASS (does not prove system registration)");
    (*d)->Release(d);
    CFRelease(factories); CFRelease(plugin); CFRelease(url);
    return 0;
}
