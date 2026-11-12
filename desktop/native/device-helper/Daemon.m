/* Root service: fixed USB collector, authenticated XPC, no command/path arguments.
 * All device/session state is confined to the main queue. */
#import "Protocol.h"
#import "Pipe.h"
#import <SystemConfiguration/SystemConfiguration.h>
#include <sys/stat.h>
#include <signal.h>
#include <unistd.h>
#include <fcntl.h>

@class RHDeviceSession;
static RHDeviceSession *owner;
static void onMain(dispatch_block_t work) {
    dispatch_async(dispatch_get_main_queue(), ^{ @autoreleasepool { work(); } });
}
static BOOL consoleUser(uid_t uid) {
    uid_t current = 0; gid_t group = 0;
    CFStringRef name = SCDynamicStoreCopyConsoleUser(NULL, &current, &group);
    if (name) CFRelease(name);
    return uid != 0 && uid == current;
}
static BOOL protectedPath(NSString *path, BOOL directory) {
    struct stat st;
    if (lstat(path.fileSystemRepresentation, &st)) return NO;
    return st.st_uid == 0 && !(st.st_mode & 0022) &&
           (directory ? S_ISDIR(st.st_mode) : S_ISREG(st.st_mode));
}

@interface RHDeviceSession : NSObject <RHService>
@property NSXPCConnection *connection;
@property NSTask *task;
@property NSFileHandle *output;
@property NSFileHandle *input;
@property dispatch_source_t reader;
@property NSMutableData *pending;
@property NSTimeInterval lastHeartbeat;
@property NSUInteger outstanding;
@property BOOL ending;
@property (copy) void (^stopReply)(void);
- (void)releaseDevice;
- (void)send:(NSString *)line;
@end
@implementation RHDeviceSession
- (void)send:(NSString *)line {
    if (self.ending || !self.connection) return;
    if (++self.outstanding > 128) { [self releaseDevice]; [self.connection invalidate]; return; }
    __weak RHDeviceSession *weak = self;
    id<RHEvents> peer = [self.connection remoteObjectProxyWithErrorHandler:^(NSError *error) {
        (void)error; onMain(^{ [weak releaseDevice]; });
    }];
    [peer event:line reply:^{ onMain(^{
        RHDeviceSession *s = weak; if (s.outstanding) s.outstanding--;
    }); }];
}
- (void)fail:(NSString *)message {
    NSData *data = [NSJSONSerialization dataWithJSONObject:@{@"type":@"error", @"message":message} options:0 error:NULL];
    [self send:[[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding]];
    [self releaseDevice];
}
- (void)releaseDevice {
    if (self.ending) return;
    self.ending = YES;
    if (self.reader) { dispatch_source_cancel(self.reader); self.reader = nil; }
    else [self.output closeFile];
    self.output = nil;
    [self.input closeFile]; self.input = nil;
    NSTask *task = self.task;
    if (task.running) {
        [task terminate];
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 3*NSEC_PER_SEC), dispatch_get_main_queue(), ^{
            if (task.running) kill(task.processIdentifier, SIGKILL);
        });
    }
    // Keep the lease until the old worker exits; a replacement must not race it.
    if (!task || !task.running) {
        if (owner == self) owner = nil;
        if (self.stopReply) { self.stopReply(); self.stopReply = nil; }
    }
}
- (void)start:(NSInteger)version reply:(void (^)(NSString *))reply {
    onMain(^{
        if (version != RH_VERSION) { reply(@"采集程序版本不匹配，请重新安装采集组件"); return; }
        if (!consoleUser(self.connection.effectiveUserIdentifier)) { reply(@"只允许当前登录用户连接遥控器"); return; }
        if (owner || self.ending) { reply(@"采集程序正在使用或释放接收器，请稍后重新检测"); return; }
        NSString *worker = [RH_DIRECTORY stringByAppendingPathComponent:@"device-capture"];
        if (!protectedPath(RH_DIRECTORY, YES) || !protectedPath(worker, NO) || !RHVerifyFile(worker, RH_WORKER) ||
            !protectedPath([RH_DIRECTORY stringByAppendingPathComponent:@"libusb-1.0.dylib"], NO) ||
            !RHVerifyFile([RH_DIRECTORY stringByAppendingPathComponent:@"libusb-1.0.dylib"], @"org.remotehub.libusb")) {
            reply(@"采集程序文件校验失败，请重新安装采集组件"); return;
        }
        NSTask *task = [NSTask new];
        task.executableURL = [NSURL fileURLWithPath:worker];
        task.arguments = @[];
        task.environment = @{@"PATH":@"/usr/bin:/bin", @"LANG":@"en_US.UTF-8"};
        NSPipe *control = [NSPipe pipe]; task.standardInput = control;
        self.input = control.fileHandleForWriting;
        if (fcntl(self.input.fileDescriptor, F_SETFL, O_NONBLOCK) < 0) {
            [self.input closeFile]; self.input = nil; reply(@"采集程序控制通道初始化失败"); return;
        }
        NSPipe *pipe = [NSPipe pipe]; task.standardOutput = pipe;
        task.standardError = [NSFileHandle fileHandleWithNullDevice];
        self.pending = [NSMutableData data]; self.task = task;
        self.output = pipe.fileHandleForReading; self.lastHeartbeat = NSProcessInfo.processInfo.systemUptime;
        owner = self;
        __weak RHDeviceSession *weak = self;
        task.terminationHandler = ^(NSTask *finished) {
            onMain(^{
                RHDeviceSession *s = weak;
                if (!s) return;
                if (!s.ending) [s fail:[NSString stringWithFormat:@"设备采集已停止（%d），请重新检测", finished.terminationStatus]];
                if (owner == s) owner = nil;
                if (s.stopReply) { s.stopReply(); s.stopReply = nil; }
            });
        };
        NSError *error = nil;
        if (![task launchAndReturnError:&error]) { [self releaseDevice]; reply(error.localizedDescription); return; }
        NSFileHandle *output = self.output;
        int fd = output.fileDescriptor;
        if (fcntl(fd, F_SETFL, O_NONBLOCK) < 0) {
            [self releaseDevice]; reply(@"采集程序数据通道初始化失败"); return;
        }
        dispatch_source_t reader = dispatch_source_create(DISPATCH_SOURCE_TYPE_READ, fd, 0, dispatch_get_main_queue());
        self.reader = reader;
        dispatch_source_set_cancel_handler(reader, ^{ [output closeFile]; });
        dispatch_source_set_event_handler(reader, ^{ @autoreleasepool {
            RHDeviceSession *s = weak;
            if (!s || s.ending) return;
            int error = 0;
            NSData *data = RHReadFD(fd, &error);
            if (!data) {
                if (error != EAGAIN && error != EWOULDBLOCK) [s fail:@"采集程序数据通道读取失败"];
                return;
            }
            if (!data.length) {
                if (s.reader) { dispatch_source_cancel(s.reader); s.reader = nil; }
                s.output = nil;
                return;
            }
            [s.pending appendData:data];
            if (s.pending.length > 16384) { [s fail:@"采集程序数据超过限制，接入已停止"]; return; }
            while (s.pending.length) {
                const void *newline = memchr(s.pending.bytes, '\n', s.pending.length);
                if (!newline) break;
                NSUInteger length = (const char *)newline - (const char *)s.pending.bytes;
                NSData *line = [s.pending subdataWithRange:NSMakeRange(0, length)];
                [s.pending replaceBytesInRange:NSMakeRange(0, length+1) withBytes:NULL length:0];
                NSString *text = [[NSString alloc] initWithData:line encoding:NSUTF8StringEncoding];
                if (!text || length > 4096) { [s fail:@"采集程序数据无效，接入已停止"]; return; }
                [s send:text];
            }
        } });
        dispatch_resume(reader);
        reply(@"");
    });
}
- (void)record:(BOOL)active reply:(void (^)(NSString *))reply {
    onMain(^{
        if (owner != self || self.ending || !self.task.running) { reply(@"采集程序尚未连接"); return; }
        char control = active ? 'S' : 'T';
        if (write(self.input.fileDescriptor, &control, 1) != 1) {
            reply(@"采集程序未能接收录音指令"); [self releaseDevice]; return;
        }
        reply(@"");
    });
}
- (void)heartbeat { onMain(^{
    self.lastHeartbeat = NSProcessInfo.processInfo.systemUptime;
}); }
- (void)stop:(void (^)(void))reply { onMain(^{
    if (!self.task.running) { [self releaseDevice]; reply(); return; }
    self.stopReply = reply;
    [self releaseDevice];
}); }
@end

@interface RHDeviceListener : NSObject <NSXPCListenerDelegate> @end
@implementation RHDeviceListener
- (BOOL)listener:(NSXPCListener *)listener shouldAcceptNewConnection:(NSXPCConnection *)connection {
    (void)listener;
    if (!consoleUser(connection.effectiveUserIdentifier)) return NO;
    RHDeviceSession *session = [RHDeviceSession new]; session.connection = connection;
    connection.exportedInterface = [NSXPCInterface interfaceWithProtocol:@protocol(RHService)];
    connection.exportedObject = session;
    connection.remoteObjectInterface = [NSXPCInterface interfaceWithProtocol:@protocol(RHEvents)];
    __weak RHDeviceSession *weak = session;
    connection.invalidationHandler = ^{ onMain(^{
        [weak releaseDevice]; weak.connection = nil;
    }); };
    connection.interruptionHandler = ^{ onMain(^{ [weak releaseDevice]; }); };
    [connection resume];
    return YES;
}
@end
int main(void) { @autoreleasepool {
    if (geteuid() != 0 || strlen(RH_CERT_SHA1) != 40) return 78;
    static NSXPCListener *listener;
    listener = [[NSXPCListener alloc] initWithMachServiceName:RH_SERVICE];
    [listener setConnectionCodeSigningRequirement:RHRequirement(RH_APP)];
    static RHDeviceListener *delegate;
    delegate = [RHDeviceListener new]; listener.delegate = delegate;
    signal(SIGTERM, SIG_IGN); signal(SIGPIPE, SIG_IGN);
    static dispatch_source_t termination, lease;
    termination = dispatch_source_create(DISPATCH_SOURCE_TYPE_SIGNAL, SIGTERM, 0, dispatch_get_main_queue());
    dispatch_source_set_event_handler(termination, ^{
        [owner releaseDevice];
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 4*NSEC_PER_SEC), dispatch_get_main_queue(), ^{ exit(0); });
    });
    dispatch_resume(termination);
    lease = dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER, 0, 0, dispatch_get_main_queue());
    dispatch_source_set_timer(lease, dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC), NSEC_PER_SEC, NSEC_PER_SEC/10);
    dispatch_source_set_event_handler(lease, ^{ @autoreleasepool {
        if (owner && !owner.ending && (!consoleUser(owner.connection.effectiveUserIdentifier) ||
            NSProcessInfo.processInfo.systemUptime - owner.lastHeartbeat > 6))
            [owner fail:@"采集程序与应用的连接已超时，正在释放接收器，请重新检测"];
    } });
    dispatch_resume(lease);
    [listener resume];
    dispatch_main();
} return 0; }
