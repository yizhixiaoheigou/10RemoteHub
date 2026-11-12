#import <Foundation/Foundation.h>
#include <errno.h>
#include <unistd.h>
// Caller owns a nonblocking descriptor. Reads at most one bounded chunk; never
// waits for a full buffer and never invokes Foundation's blocking pipe reads.
static NSData *RHReadFD(int fd, int *error) {
    unsigned char buffer[4096];
    ssize_t length;
    do { length = read(fd, buffer, sizeof buffer); } while (length < 0 && errno == EINTR);
    *error = length < 0 ? errno : 0;
    return length < 0 ? nil : [NSData dataWithBytes:buffer length:(NSUInteger)length];
}
