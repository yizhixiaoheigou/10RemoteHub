#import "../device-helper/Pipe.h"
#include <fcntl.h>
int main(void) { @autoreleasepool {
    static int ends[2];
    if (pipe(ends) || fcntl(ends[0], F_SETFL, O_NONBLOCK) < 0) return 4;
    static dispatch_source_t reader;
    reader = dispatch_source_create(DISPATCH_SOURCE_TYPE_READ, ends[0], 0, dispatch_get_main_queue());
    dispatch_source_set_event_handler(reader, ^{ @autoreleasepool {
        int error = 0;
        NSData *data = RHReadFD(ends[0], &error);
        if (data.length != 5 || error) exit(1);
        close(ends[0]); close(ends[1]);
        if (RHReadFD(ends[0], &error) != nil || error != EBADF) exit(3);
        exit(0);
    } });
    dispatch_resume(reader);
    if (write(ends[1], "ready", 5) != 5) return 5;
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC), dispatch_get_main_queue(), ^{
        fputs("small collector event was buffered instead of delivered\n", stderr); exit(2);
    });
    dispatch_main();
} }
