/* Fixed-size, timestamped stereo ring. No allocations or locks in audio I/O.
 * Untouched/overwritten sample times return silence, never stale microphone data.
 */
#include "loopback.h"
#include <stdatomic.h>
#include <string.h>
#include <math.h>
#define FRAMES 65536
typedef struct { _Atomic uint64_t stamp; _Atomic uint64_t samples; } Slot;
static Slot ring[FRAMES];
_Static_assert(ATOMIC_LLONG_LOCK_FREE == 2, "Audio ring requires lock-free 64-bit atomics");
void RHLoopbackReset(void) {
    for (uint32_t i=0;i<FRAMES;i++) atomic_store_explicit(&ring[i].stamp,0,memory_order_release);
}
void RHLoopbackWrite(int64_t frame,uint32_t count,const float *data) {
    for(uint32_t i=0;i<count;i++) {
        int64_t at=frame+i; if(at<0) continue;
        Slot *slot=&ring[(uint64_t)at%FRAMES];
        float pair[2]={isfinite(data[2*i])?data[2*i]:0,isfinite(data[2*i+1])?data[2*i+1]:0};
        uint64_t bits; memcpy(&bits,pair,sizeof(bits));
        atomic_store_explicit(&slot->stamp,0,memory_order_release);
        atomic_store_explicit(&slot->samples,bits,memory_order_relaxed);
        atomic_store_explicit(&slot->stamp,(uint64_t)at+1,memory_order_release);
    }
}
void RHLoopbackRead(int64_t frame,uint32_t count,float *data) {
    for(uint32_t i=0;i<count;i++) {
        int64_t at=frame+i; uint64_t bits=0;
        if(at>=0) {
            Slot *slot=&ring[(uint64_t)at%FRAMES];
            uint64_t expected=(uint64_t)at+1;
            if(atomic_load_explicit(&slot->stamp,memory_order_acquire)==expected) {
                bits=atomic_load_explicit(&slot->samples,memory_order_relaxed);
                if(atomic_load_explicit(&slot->stamp,memory_order_acquire)!=expected) bits=0;
            }
        }
        memcpy(data+2*i,&bits,sizeof(bits));
    }
}
