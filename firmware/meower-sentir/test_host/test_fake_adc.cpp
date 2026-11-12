#include <cstdio>
#include <cstring>
#include <cassert>
#include <cmath>
#include "sentir_fake_adc.h"
int64_t g_fake_now = 0;
volatile uint8_t g_adsCount = 2;
static int32_t s24(const uint8_t* p){ int32_t v=(p[0]<<16)|(p[1]<<8)|p[2]; return (v<<8)>>8; }
int main(){
  uint8_t rx[54], tx[54] = {0};
  // ID via daisy read (30 bytes), como read_Register_Daisy
  tx[0]=0x20; tx[1]=0; sentir_fake_xfer('B',30,tx,rx);
  printf("ID mestre=0x%02X escravo=0x%02X\n", rx[2], rx[29]);
  assert(rx[2]==0x3E && rx[29]==0x00);           // 1 chip emulado
  // WREG CONFIG1 = 0xB4 (1000 SPS, daisy, clk out) no mestre; ler de volta
  uint8_t w[3]={0x41,0x00,0xB4}; sentir_fake_xfer('M',3,w,rx);
  uint8_t r[3]={0x21,0x00,0x00}; sentir_fake_xfer('M',3,r,rx); assert(rx[2]==0xB4);
  // CH1SET ganho 24, entrada normal (0x60)
  for(int c=0;c<8;c++){ uint8_t wc[3]={(uint8_t)(0x45+c),0,0x60}; sentir_fake_xfer('B',3,wc,rx);}  
  memset(tx,0,54);
  double sum=0, sq=0; int N=1000; int pd_hi=0;
  for(int i=0;i<N;i++){ g_fake_now = i*1000; sentir_fake_xfer('B',54,tx,rx);
    assert((rx[0]>>4)==0xC);                         // header de status
    pd_hi += rx[2]&1;
    double uv = s24(rx+3)*(4.5/8388608.0*1e6)/24.0; sum+=uv; sq+=uv*uv;
    for(int k=27;k<54;k++) assert(rx[k]==0);       // escravo ausente
  }
  double rms = sqrt(sq/N - (sum/N)*(sum/N));
  printf("CH1 RMS=%.2f uV (esperado ~14.8 alfa + 3.5 rede + 3 ruido -> ~15.5)  fotodiodo alto=%d/%d\n", rms, pd_hi, N);
  assert(rms>12 && rms<20); assert(pd_hi>450 && pd_hi<550);
  puts("OK");
}
