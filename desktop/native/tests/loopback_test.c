#include "../loopback.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
int main(void) {
    float input[]={.25f,-.5f,.125f,.75f}, output[4];
    RHLoopbackReset(); RHLoopbackRead(0,2,output);
    for(int i=0;i<4;i++) assert(output[i]==0);
    RHLoopbackWrite(100,2,input); RHLoopbackRead(100,2,output);
    for(int i=0;i<4;i++) assert(output[i]==input[i]);
    RHLoopbackRead(99,2,output); assert(output[0]==0 && output[1]==0 && output[2]==.25f);
    RHLoopbackWrite(100+65536,2,input); RHLoopbackRead(100,2,output);
    for(int i=0;i<4;i++) assert(output[i]==0);
    RHLoopbackRead(-1,2,output); for(int i=0;i<4;i++) assert(output[i]==0);
    float invalid[]={NAN,INFINITY}; RHLoopbackWrite(4,1,invalid); RHLoopbackRead(4,1,output);
    assert(output[0]==0 && output[1]==0);
    RHLoopbackReset(); RHLoopbackRead(100+65536,2,output); for(int i=0;i<4;i++) assert(output[i]==0);
    puts("loopback: silence, timestamps, wrap, invalid samples, reset passed");
    return 0;
}
