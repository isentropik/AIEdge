"""Compare production transforms byte-for-byte with the preserved column-order baseline."""
import argparse, os, subprocess, tempfile
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--zig-python');p.add_argument('--cxx',default='c++');a=p.parse_args()
root=Path(__file__).resolve().parents[2]
old=Path(__file__).with_name('rotation-baseline.cpp').read_text(encoding='utf-8')
new=(root/'code/components/jomjol_image_proc/CRotateImage.cpp').read_text(encoding='utf-8')
def body(s): return '\n'.join(line for line in s.splitlines() if not line.startswith('#include'))
fixture=r'''
#include <string>
#include <vector>
#include <cassert>
#include <cstring>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <utility>
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
using stbi_uc=unsigned char;
const int MALLOC_CAP_SPIRAM=0;
unsigned char* malloc_psram_heap(std::string,int n,int){return static_cast<unsigned char*>(std::malloc(n));}
void free_psram_heap(std::string,unsigned char*p){std::free(p);}
struct CImageBasis {
 unsigned char*rgb_image=nullptr;int channels=3,width=0,height=0,bpp=3;bool externalImage=false,islocked=false;
 std::vector<unsigned char> bytes;
 CImageBasis(std::string){}
 CImageBasis(int w,int h,int c):channels(c),width(w),height(h),bytes(w*h*c){rgb_image=bytes.data();}
 unsigned char*RGBImageLock(){assert(!islocked);islocked=true;return rgb_image;}
 void RGBImageRelease(){assert(islocked);islocked=false;}
 void memCopy(unsigned char*s,unsigned char*d,int n){std::memcpy(d,s,n);}
};
'''
decl=r'''
class CRotateImage:public CImageBasis {public:
 CImageBasis*ImageTMP,*ImageOrg;bool doflip;
 CRotateImage(std::string,CImageBasis*,CImageBasis*,bool);
 void Rotate(float,int,int);void Rotate(float);
 void RotateAntiAliasing(float,int,int);void RotateAntiAliasing(float);
 void Translate(int,int);
};
'''
main=r'''
int main(){int cases=0;
 for(auto size:{std::pair<int,int>{13,9},{144,146},{640,480}})
 for(int channels:{1,3})for(bool temporary:{false,true})for(bool flip:{false,true})
 for(int operation:{0,1,2})for(float angle:{0.f,.3f,-.3f,1.f,-2.f,45.f,90.f,180.f}) {
  if(operation==2 && flip)continue;
  CImageBasis a(size.first,size.second,channels),b(size.first,size.second,channels);
  CImageBasis ta(size.first,size.second,channels),tb(size.first,size.second,channels);
  for(size_t i=0;i<a.bytes.size();++i)a.bytes[i]=b.bytes[i]=static_cast<unsigned char>((i*37+(i/size.first)*11)%256);
  before::CRotateImage old("old",&a,temporary?&ta:nullptr,flip);
  after::CRotateImage now("new",&b,temporary?&tb:nullptr,flip);
  if(operation==0){old.Rotate(angle);now.Rotate(angle);}
  if(operation==1){old.RotateAntiAliasing(angle);now.RotateAntiAliasing(angle);}
  if(operation==2){old.Translate(int(angle),-int(angle));now.Translate(int(angle),-int(angle));}
  assert(a.bytes==b.bytes && a.width==b.width && a.height==b.height);
  assert(!old.islocked&&!now.islocked&&!ta.islocked&&!tb.islocked);++cases;
 }
 std::cout<<cases<<" exact rotation/antialias/translation comparisons passed\n";
}
'''
with tempfile.TemporaryDirectory(prefix='aiedge-rotation-') as folder:
 out=Path(folder);cpp=out/'rotation.cpp';exe=out/('rotation.exe' if os.name=='nt' else 'rotation')
 cpp.write_text(fixture+'\nnamespace before {\n'+decl+body(old)+'\n}\nnamespace after {\n'+decl+body(new)+'\n}\n'+main,encoding='utf-8')
 compiler=[a.zig_python,'-m','ziglang','c++'] if a.zig_python else [a.cxx]
 subprocess.run(compiler+['-std=c++11','-O2','-ffp-contract=off','-UNDEBUG',str(cpp),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
