/* Loaded in the ordinary GUI process. No subprocess elevation, no registration
 * on startup. Only an explicitly opened installer changes the system. */
#import "Protocol.h"
#include <sys/stat.h>

@interface RHDeviceClient : NSObject <RHEvents>
@property NSXPCConnection *connection;
@property NSMutableArray<NSString *> *events;
@property BOOL closed;
@property dispatch_source_t heartbeatTimer;
- (void)push:(NSString *)line;
- (void)fail:(NSString *)message;
- (void)startHeartbeat;
- (void)heartbeat;
- (void)stopHeartbeat;
@end
@implementation RHDeviceClient
- (instancetype)init { if ((self = [super init])) self.events = [NSMutableArray array]; return self; }
- (void)heartbeat {
    @synchronized (self) {
        if (self.closed || !self.connection) return;
        __weak RHDeviceClient *weak = self;
        id<RHService> proxy = [self.connection remoteObjectProxyWithErrorHandler:^(NSError *error) {
            [weak fail:[@"采集程序：" stringByAppendingString:error.localizedDescription]];
        }];
        [proxy heartbeat];
    }
}
- (void)startHeartbeat {
    // This queue continues even when the GUI/Python thread is occupied.
    @synchronized (self) {
        if (self.closed || self.heartbeatTimer) return;
        self.heartbeatTimer = dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER, 0, 0,
                                                     dispatch_get_global_queue(QOS_CLASS_UTILITY, 0));
        __weak RHDeviceClient *weak = self;
        dispatch_source_set_timer(self.heartbeatTimer, dispatch_time(DISPATCH_TIME_NOW, 2*NSEC_PER_SEC),
                                  2*NSEC_PER_SEC, NSEC_PER_SEC/10);
        dispatch_source_set_event_handler(self.heartbeatTimer, ^{ @autoreleasepool { [weak heartbeat]; } });
        dispatch_resume(self.heartbeatTimer);
    }
}
- (void)stopHeartbeat {
    @synchronized (self) {
        if (self.heartbeatTimer) dispatch_source_cancel(self.heartbeatTimer);
        self.heartbeatTimer = nil;
    }
}
- (void)dealloc { if (_heartbeatTimer) dispatch_source_cancel(_heartbeatTimer); }
- (void)push:(NSString *)line {
    BOOL overflow = NO;
    @synchronized (self) {
        if (self.closed) return;
        if (self.events.count >= 256 || [line lengthOfBytesUsingEncoding:NSUTF8StringEncoding] > 4096) {
            [self.events removeAllObjects];
            [self.events addObject:@"{\"type\":\"error\",\"message\":\"采集数据处理积压，连接已停止，请重新检测\"}"];
            self.closed = YES; overflow = YES;
        } else [self.events addObject:line];
    }
    if (overflow) { [self stopHeartbeat]; [self.connection invalidate]; }
}
- (void)fail:(NSString *)message {
    NSData *data = [NSJSONSerialization dataWithJSONObject:@{@"type":@"error", @"message":message} options:0 error:NULL];
    @synchronized (self) {
        if (self.closed) return;
        [self.events removeAllObjects];
        [self.events addObject:[[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding]];
        self.closed = YES;
    }
    [self stopHeartbeat]; [self.connection invalidate];
}
- (void)event:(NSString *)line reply:(void (^)(void))reply { [self push:line]; reply(); }
@end
static RHDeviceClient *current;

// 0 installed, 1 missing, 2 unsigned build, 3 invalid permissions/signature.
int rh_device_status(void) { @autoreleasepool {
    if (strlen(RH_CERT_SHA1) != 40) return 2;
    NSString *path = [RH_DIRECTORY stringByAppendingPathComponent:@"device-helper"];
    struct stat st, dir;
    if (lstat(path.fileSystemRepresentation, &st)) return 1;
    if (lstat(RH_DIRECTORY.fileSystemRepresentation, &dir) || !S_ISDIR(dir.st_mode) || dir.st_uid || (dir.st_mode & 0022) ||
        !S_ISREG(st.st_mode) || st.st_uid || (st.st_mode & 0022) || !RHVerifyFile(path, RH_SERVICE)) return 3;
    return 0;
} }
int rh_device_disconnect(void) { @autoreleasepool {
    RHDeviceClient *c = current; current = nil;
    if (!c) return 0;
    @synchronized (c) { c.closed = YES; [c.events removeAllObjects]; }
    [c stopHeartbeat];
    dispatch_semaphore_t done = dispatch_semaphore_create(0);
    __block BOOL released = NO;
    id<RHService> proxy = [c.connection remoteObjectProxyWithErrorHandler:^(NSError *error) {
        (void)error; dispatch_semaphore_signal(done);
    }];
    [proxy stop:^{ released = YES; dispatch_semaphore_signal(done); }];
    long timeout = dispatch_semaphore_wait(done, dispatch_time(DISPATCH_TIME_NOW, 4*NSEC_PER_SEC));
    [c.connection invalidate]; c.connection = nil;
    return !timeout && released ? 0 : -1;
} }
int rh_device_connect(void) { @autoreleasepool {
    rh_device_disconnect();
    int status = rh_device_status(); if (status) return status;
    RHDeviceClient *c = [RHDeviceClient new]; current = c;
    NSXPCConnection *connection = [[NSXPCConnection alloc] initWithMachServiceName:RH_SERVICE options:NSXPCConnectionPrivileged];
    c.connection = connection;
    [connection setCodeSigningRequirement:RHRequirement(RH_SERVICE)];
    connection.remoteObjectInterface = [NSXPCInterface interfaceWithProtocol:@protocol(RHService)];
    connection.exportedInterface = [NSXPCInterface interfaceWithProtocol:@protocol(RHEvents)];
    connection.exportedObject = c;
    __weak RHDeviceClient *weak = c;
    connection.invalidationHandler = ^{ [weak fail:@"采集程序连接已断开，请确认采集组件已安装，并重新检测"]; };
    connection.interruptionHandler = ^{ [weak fail:@"采集程序已中断，正在释放接收器，请重新检测"]; };
    [connection resume];
    id<RHService> proxy = [connection remoteObjectProxyWithErrorHandler:^(NSError *error) {
        [weak fail:[@"采集程序连接失败：" stringByAppendingString:error.localizedDescription]];
    }];
    [proxy start:RH_VERSION reply:^(NSString *error) { if (error.length) [weak fail:[@"采集程序：" stringByAppendingString:error]]; }];
    [c startHeartbeat];
    return 0;
} }
void rh_device_record(int active) { @autoreleasepool {
    RHDeviceClient *c = current; if (!c || c.closed) return;
    __weak RHDeviceClient *weak = c;
    id<RHService> proxy = [c.connection remoteObjectProxyWithErrorHandler:^(NSError *error) { [weak fail:[@"采集程序：" stringByAppendingString:error.localizedDescription]]; }];
    [proxy record:active != 0 reply:^(NSString *error) { if (error.length) [weak fail:error]; }];
} }
void rh_device_heartbeat(void) { @autoreleasepool {
    [current heartbeat];
} }
// Caller owns the buffer. 1 event, 0 empty, -1 insufficient capacity (event retained).
int rh_device_next(char *buffer, size_t capacity) { @autoreleasepool {
    RHDeviceClient *c = current; if (!c) return 0;
    @synchronized (c) {
        if (!c.events.count) return 0;
        const char *line = c.events[0].UTF8String;
        size_t length = strlen(line);
        if (!buffer || length + 1 > capacity) return -1;
        memcpy(buffer, line, length+1); [c.events removeObjectAtIndex:0]; return 1;
    }
} }
