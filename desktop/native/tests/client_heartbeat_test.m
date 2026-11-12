// No XPC service, USB, signing, registration or authorization is touched.
#import "../device-helper/Client.m"
#include <assert.h>

@interface FakeConnection : NSObject
@property NSUInteger beats;
- (id)remoteObjectProxyWithErrorHandler:(void (^)(NSError *))handler;
- (void)heartbeat;
- (void)invalidate;
@end
@implementation FakeConnection
- (id)remoteObjectProxyWithErrorHandler:(void (^)(NSError *))handler { (void)handler; return self; }
- (void)heartbeat { @synchronized (self) { self.beats++; } }
- (void)invalidate {}
@end

int main(void) { @autoreleasepool {
    FakeConnection *connection = [FakeConnection new];
    RHDeviceClient *client = [RHDeviceClient new];
    client.connection = (NSXPCConnection *)connection;
    [client startHeartbeat];
    // Deliberately stall the main thread longer than the daemon's 6 s lease.
    [NSThread sleepForTimeInterval:6.5];
    @synchronized (connection) { assert(connection.beats >= 3); }
    [client stopHeartbeat];
    NSUInteger stopped;
    @synchronized (connection) { stopped = connection.beats; }
    [NSThread sleepForTimeInterval:2.3];
    @synchronized (connection) { assert(connection.beats == stopped); }
    [client startHeartbeat];
    [client fail:@"simulated disconnect"];
    assert(client.closed && !client.heartbeatTimer && client.events.count == 1);
    puts("CLIENT_HEARTBEAT_PASS");
    return 0;
} }
