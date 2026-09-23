"""Execute the actual alignment method with image-operation substitutes."""
from pathlib import Path
import os,sys,tempfile,subprocess
root=Path(__file__).resolve().parents[2];out=Path(tempfile.mkdtemp(prefix='aiedge-preview-'))
text=(root/'code/components/jomjol_flowcontroll/ClassFlowAlignment.cpp').read_text()
body=text[text.index('bool ClassFlowAlignment::doFlow(string time)'):text.index('void ClassFlowAlignment::SaveReferenceAlignmentValues()')]
prefix=r'''
#include <string>
#include <cassert>
#include <cstdlib>
#include <new>
using std::string;
#define ALGROI_LOAD_FROM_MEM_AS_JPG
constexpr int MALLOC_CAP_8BIT=1,MALLOC_CAP_SPIRAM=2,ESP_LOG_ERROR=1;
const char* TAG="ALIGN";
struct ImageData{size_t size;};
static int encodes=0,rawEncodes=0,rotates=0,aligns=0,draws=0;static bool failTemporary=false;
struct CImageBasis{
 int width=640,height=480;bool raw=true;
 CImageBasis(){} CImageBasis(const char*,CImageBasis*p):width(p->width),height(p->height),raw(false){}
 static void*operator new(size_t n) noexcept{return failTemporary?nullptr:malloc(n);}
 static void operator delete(void*p) noexcept{free(p);}
 void writeToMemoryAsJPG(ImageData*i,int quality){assert(quality==90);++encodes;if(raw)++rawEncodes;i->size=123;}
 void SaveToFile(const string&){}
};
struct Reference{int alignment_algo=3;};
struct CAlignAndCutImage:CImageBasis{
 CAlignAndCutImage(const char*,CImageBasis*p,CImageBasis*):CImageBasis("",p){}
 bool Align(Reference*,Reference*){++aligns;return true;}
};
struct CRotateImage{CRotateImage(const char*,CAlignAndCutImage*,CImageBasis*,bool){}void Rotate(float){++rotates;}void RotateAntiAliasing(float){++rotates;}};
struct Logger{void WriteToFile(int,const char*,const char*){}void WriteHeapInfo(const char*){}}LogFile;
struct Flow{void DigitDrawROI(CImageBasis*){++draws;}void AnalogDrawROI(CImageBasis*){++draws;}}flowctrl;
void*heap_caps_realloc(void*p,size_t n,int){return realloc(p,n);}
string FormatFileName(const char*p){return p;}
struct ClassFlowAlignment{
 ImageData*AlgROI;CImageBasis*ImageBasis;CImageBasis*ImageTMP=nullptr;CAlignAndCutImage*AlignAndCutImage=nullptr;
 bool initialflip=false,use_antialiasing=false,SaveAllFiles=false;float initialrotate=.3f;Reference References[2];
 bool doFlow(string);void DrawRef(CImageBasis*){++draws;}void SaveReferenceAlignmentValues(){}bool LoadReferenceAlignmentValues(){return true;}
};
'''
main=r'''
int main(){ImageData preview{999};CImageBasis raw;ClassFlowAlignment a;a.AlgROI=&preview;a.ImageBasis=&raw;
 assert(a.doFlow("now"));assert(encodes==1&&rawEncodes==0&&preview.size==123&&rotates==1&&draws==2&&aligns==0);
 a.References[0].alignment_algo=0;assert(a.doFlow("next"));assert(encodes==2&&rawEncodes==0&&aligns==1&&draws==5);
 preview.size=999;failTemporary=true;assert(!a.doFlow("failed"));assert(preview.size==0&&encodes==2);failTemporary=false;
 delete a.AlignAndCutImage;
}
'''
(out/'test.cpp').write_text(prefix+body+main)
env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(out/'cache'),ZIG_LOCAL_CACHE_DIR=str(out/'local'))
exe=out/'test.exe';subprocess.run([sys.executable,'-m','ziglang','c++','-std=c++11','-O2','-UNDEBUG',str(out/'test.cpp'),'-o',str(exe)],env=env,check=True)
subprocess.run([str(exe)],check=True)
print('PASS: actual alignment method encodes one annotated preview, preserves rotation/alignment calls, clears stale length on allocation failure; image math substituted')
