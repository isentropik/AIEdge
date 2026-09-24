"""Sparse sampler boundary and dense-anchor invariants; synthetic pixels only."""
from pathlib import Path
import os,subprocess,sys,tempfile
ROOT=Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='aiedge-sparse-') as folder:
 out=Path(folder)
 (out/'test.cpp').write_text(r'''#include "PolarWarp.h"
#include <vector>
#include <cassert>
#include <limits>
int main(){
 const int width=12,height=12;
 std::vector<uint8_t> source(width*height*3);
 for(size_t i=0;i<source.size();++i)source[i]=(i*37+i/7)%256;
 const auto original=source;
 const double transforms[][6]={{1,0,0,0,1,0},{.998,.04,-.6,-.04,.998,.3},{1,0,-20,0,1,-20}};
 for(const auto& matrix:transforms)for(int w=1;w<=9;++w)for(int h=1;h<=9;++h){
  std::vector<uint8_t> dense(w*h*3),sparse(w*h*3+2,173);
  assert(polar::warpCrop(source.data(),width,height,matrix,1,1,w,h,dense.data()));
  assert(polar::warpCrop(source.data(),width,height,matrix,1,1,w,h,sparse.data()+1,true));
  assert(sparse.front()==173&&sparse.back()==173&&source==original);
  for(int y=0;y<h;y+=2)for(int x=0;x<w;x+=2)for(int c=0;c<3;++c)
   assert(sparse[1+3*(y*w+x)+c]==dense[3*(y*w+x)+c]);
  for(int y=0;y<h;++y)for(int x=0;x<w;++x)for(int c=0;c<3;++c){
   int left=x-x%2,right=std::min(left+2,(w-1)/2*2);
   int top=y-y%2,bottom=std::min(top+2,(h-1)/2*2);
   double tx=(x%2)*.5,ty=(y%2)*.5;
   auto value=[&](int xx,int yy){return dense[3*(yy*w+xx)+c];};
   double expected=(1-ty)*((1-tx)*value(left,top)+tx*value(right,top))+ty*((1-tx)*value(left,bottom)+tx*value(right,bottom));
   assert(sparse[1+3*(y*w+x)+c]==static_cast<uint8_t>(expected));
  }
 }
 double invalid[6]={1,0,0,0,1,std::numeric_limits<double>::quiet_NaN()};
 uint8_t out[3]={};assert(!polar::warpCrop(source.data(),width,height,invalid,0,0,1,1,out,true));
 assert(!polar::warpCrop(nullptr,width,height,transforms[0],0,0,1,1,out,true));
 assert(!polar::warpCrop(source.data(),width,height,transforms[0],0,0,1,1,source.data(),true));
}
''')
 env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(out/'cache'),ZIG_LOCAL_CACHE_DIR=str(out/'local'))
 exe=out/'test.exe'
 subprocess.run([sys.executable,'-m','ziglang','c++','-std=c++11','-O2','-UNDEBUG','-ffp-contract=off','-I'+str(ROOT/'code/components/jomjol_tfliteclass'),str(out/'test.cpp'),'-o',str(exe)],check=True,env=env)
 subprocess.run([str(exe)],check=True)
 print('243 crop/transform cases passed: anchors, interpolation, edge sizes, guard bytes and invalid input.')
