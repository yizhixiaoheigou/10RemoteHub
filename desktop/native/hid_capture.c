/* Device-specific macOS HID capture. No USB reset or global keyboard hook.
 * Only runs after the user enables a selected profile in the app.
 * stdout is line-delimited JSON; stderr carries failures. */
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/hid/IOHIDManager.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static volatile sig_atomic_t stopping;
static int fixed_receiver;
static void stop(int sig) { (void)sig; stopping = 1; }
static void removed(void *ctx, IOReturn result, void *sender) {
    (void)ctx; (void)result; (void)sender;
    puts("{\"type\":\"removed\"}"); stopping=1;
}
static void value(void *ctx, IOReturn result, void *sender, IOHIDValueRef input) {
    (void)ctx; (void)sender;
    if (result != kIOReturnSuccess) return;
    IOHIDElementRef element = IOHIDValueGetElement(input);
    uint32_t page = IOHIDElementGetUsagePage(element), usage = IOHIDElementGetUsage(element);
    if ((page != 7 && page != 12 && page != 9) || !usage || usage>0xffff || (page == 7 && usage < 4)) return;
    if (fixed_receiver && page==7) return; /* decoded once from the raw report */
    printf("{\"type\":\"key\",\"trigger\":\"hid:%u:%u\",\"down\":%s}\n", page, usage,
           IOHIDValueGetIntegerValue(input) ? "true" : "false");
}
static void keyboard_report(void *ctx, IOReturn result, void *sender, IOHIDReportType type,
                            uint32_t id, uint8_t *data, CFIndex length) {
    (void)ctx; (void)sender; (void)type;
    if(result || id || length!=8)return;
    printf("{\"type\":\"keyboard\",\"hex\":\"");
    for(CFIndex i=0;i<length;i++)printf("%02x",data[i]);
    puts("\"}");
}
static int prop(IOHIDDeviceRef d, CFStringRef k) {
    CFTypeRef n = IOHIDDeviceGetProperty(d, k); int x=0;
    if (n && CFGetTypeID(n)==CFNumberGetTypeID()) CFNumberGetValue(n,kCFNumberIntType,&x);
    return x;
}
int main(int argc, char **argv) {
    if (argc < 3 || argc > 4) { fprintf(stderr,"usage: hid_capture VID PID [SERIAL]\n"); return 2; }
    int vid=(int)strtol(argv[1],NULL,0), pid=(int)strtol(argv[2],NULL,0);
    fixed_receiver=(vid==0x0416 && pid==0x0602);
    if (vid<=0 || vid>65535 || pid<=0 || pid>65535) return 2;
    signal(SIGINT, stop); signal(SIGTERM, stop); setbuf(stdout,NULL);
    IOHIDManagerRef manager = IOHIDManagerCreate(kCFAllocatorDefault, 0);
    CFNumberRef v=CFNumberCreate(NULL,kCFNumberIntType,&vid), p=CFNumberCreate(NULL,kCFNumberIntType,&pid);
    const void *keys[]={CFSTR(kIOHIDVendorIDKey),CFSTR(kIOHIDProductIDKey)};
    const void *vals[]={v,p};
    CFDictionaryRef match=CFDictionaryCreate(NULL,keys,vals,2,&kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
    IOHIDManagerSetDeviceMatching(manager,match);
    CFRelease(match); CFRelease(v); CFRelease(p);
    /* Enumerate, retain devices through the set, then release manager, matching
       the receiver callback ownership verified in hid_probe.c. */
    CFSetRef set=IOHIDManagerCopyDevices(manager);
    CFRelease(manager);
    if (!set || !CFSetGetCount(set)) { fprintf(stderr,"Device not connected\n"); if(set)CFRelease(set); return 3; }
    CFIndex count=CFSetGetCount(set);
    IOHIDDeviceRef *devices=calloc((size_t)count,sizeof(*devices));
    unsigned char *opened=calloc((size_t)count,1);
    unsigned char *buffers=calloc((size_t)count,4096);
    if (!devices || !opened || !buffers) { free(devices); free(opened); free(buffers); CFRelease(set); return 4; }
    CFSetGetValues(set,(const void**)devices);
    int ok=0,failed=0;
    for (CFIndex i=0;i<count;i++) {
        IOHIDDeviceRef d=devices[i];
        if (argc==4 && argv[3][0]) {
            CFTypeRef serial=IOHIDDeviceGetProperty(d,CFSTR(kIOHIDSerialNumberKey)); char s[512]={0};
            if (!serial || CFGetTypeID(serial)!=CFStringGetTypeID() || !CFStringGetCString(serial,s,sizeof(s),kCFStringEncodingUTF8) || strcmp(s,argv[3])) continue;
        }
        int page=prop(d,CFSTR(kIOHIDPrimaryUsagePageKey));
        /* Never seize the vendor voice interface in ordinary key mode. */
        if (page>=0xff00) continue;
        IOReturn rc=IOHIDDeviceOpen(d,kIOHIDOptionsTypeSeizeDevice);
        if(rc) {
            fprintf(stderr,"HID exclusive open failed: 0x%x. Keyboard seizure needs privilege in addition to Input Monitoring.\n",rc);
            failed++; continue;
        }
        opened[i]=1; ok++;
        IOHIDDeviceRegisterInputValueCallback(d,value,NULL);
        if(fixed_receiver && page==1 && prop(d,CFSTR(kIOHIDPrimaryUsageKey))==6)
            IOHIDDeviceRegisterInputReportCallback(d,buffers+i*4096,4096,keyboard_report,NULL);
        IOHIDDeviceRegisterRemovalCallback(d,removed,NULL);
        IOHIDDeviceScheduleWithRunLoop(d,CFRunLoopGetCurrent(),kCFRunLoopDefaultMode);
    }
    printf("{\"type\":\"ready\",\"interfaces\":%d}\n",failed?0:ok);
    while(ok && !failed && !stopping) CFRunLoopRunInMode(kCFRunLoopDefaultMode,0.1,false);
    for(CFIndex i=0;i<count;i++) if(opened[i]) {
        IOHIDDeviceUnscheduleFromRunLoop(devices[i],CFRunLoopGetCurrent(),kCFRunLoopDefaultMode);
        IOHIDDeviceClose(devices[i],kIOHIDOptionsTypeSeizeDevice);
    }
    free(buffers); free(opened); free(devices); CFRelease(set);
    return ok && !failed ? 0 : 5;
}
