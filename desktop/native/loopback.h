#ifndef RH_LOOPBACK_H
#define RH_LOOPBACK_H
#include <stdint.h>
#define RH_LOOPBACK_DELAY 1024
void RHLoopbackReset(void);
void RHLoopbackWrite(int64_t frame, uint32_t count, const float *stereo);
void RHLoopbackRead(int64_t frame, uint32_t count, float *stereo);
#endif
