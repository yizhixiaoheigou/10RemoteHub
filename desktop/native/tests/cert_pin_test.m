// Usage: cert_pin_test <signed-file> <identifier> ; RH_CERT_SHA1 is set at compile time.
// Exit 0 when Protocol.h's pinned requirement accepts the file, 1 when it rejects it.
#import "../device-helper/Protocol.h"
int main(int argc, char **argv) {
    @autoreleasepool {
        if (argc != 3) return 2;
        return RHVerifyFile(@(argv[1]), @(argv[2])) ? 0 : 1;
    }
}
