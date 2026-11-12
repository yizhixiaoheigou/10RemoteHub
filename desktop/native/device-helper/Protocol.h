#import <Foundation/Foundation.h>
#import <Security/Security.h>
// SHA-1 of the signing certificate shared by the App and collector. It pins
// one certificate, Apple-issued or the project's own, not a Team ID.
#ifndef RH_CERT_SHA1
#define RH_CERT_SHA1 ""
#endif
#define RH_SERVICE @"org.remotehub.device-helper"
#define RH_APP @"org.remotehub.desktop"
#define RH_WORKER @"org.remotehub.device-capture"
#define RH_DIRECTORY @"/Library/PrivilegedHelperTools/10RemoteHub"
#define RH_VERSION 2

@protocol RHEvents
- (void)event:(NSString *)line reply:(void (^)(void))reply;
@end
@protocol RHService
- (void)start:(NSInteger)version reply:(void (^)(NSString *error))reply;
- (void)heartbeat;
- (void)record:(BOOL)active reply:(void (^)(NSString *error))reply;
- (void)stop:(void (^)(void))reply;
@end

static NSString *RHRequirement(NSString *identifier) {
    return [NSString stringWithFormat:@"identifier \"%@\" and certificate leaf = H\"%s\"", identifier, RH_CERT_SHA1];
}
static BOOL RHVerifyFile(NSString *path, NSString *identifier) {
    if (strlen(RH_CERT_SHA1) != 40) return NO;
    SecStaticCodeRef code = NULL; SecRequirementRef requirement = NULL;
    OSStatus status = SecStaticCodeCreateWithPath((__bridge CFURLRef)[NSURL fileURLWithPath:path], kSecCSDefaultFlags, &code);
    if (!status) status = SecRequirementCreateWithString((__bridge CFStringRef)RHRequirement(identifier), kSecCSDefaultFlags, &requirement);
    if (!status) status = SecStaticCodeCheckValidity(code, kSecCSStrictValidate | kSecCSCheckAllArchitectures, requirement);
    if (requirement) CFRelease(requirement);
    if (code) CFRelease(code);
    return status == errSecSuccess;
}
