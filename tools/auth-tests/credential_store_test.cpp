#include "credential_test_backend.h"
int main(){
 Fake f;Credential c(f);assert(c.state()==State::Uninitialized);assert(!c.save(password,sizeof(password)-1));assert(!c.verify(password,sizeof(password)-1));assert(c.load()==State::NeedsSetup);
 for(size_t n=0;n<12;++n)assert(!c.save(password,n));assert(!c.save(nullptr,20));assert(!c.save(password,129));uint8_t control[12]={};assert(!c.save(control,12));assert(f.writes==0);
 assert(c.save(password,sizeof(password)-1));assert(c.state()==State::Ready&&c.verify(password,sizeof(password)-1));assert(!c.verify(other,sizeof(other)-1));assert(!c.verify(nullptr,12));assert(!c.verify(password,129));const auto original=f.disk;
 assert(std::search(f.disk.begin(),f.disk.end(),password,password+sizeof(password)-1)==f.disk.end());
 {Credential reboot(f);assert(reboot.load()==State::Ready&&reboot.verify(password,sizeof(password)-1));}
 for(int mode=0;mode<3;++mode){f.randomError=mode==0;f.deriveError=mode==1;f.digestError=mode==2;assert(!c.save(other,sizeof(other)-1));assert(c.state()==State::Ready&&f.disk==original);f.randomError=f.deriveError=f.digestError=false;assert(c.verify(password,sizeof(password)-1));}
 for(size_t i=0;i<credentialBytes;++i){f.disk=original;f.disk[i]^=1;assert(c.load()==State::StorageError);assert(!c.verify(password,sizeof(password)-1));assert(!c.save(password,sizeof(password)-1));}
 for(size_t n:{size_t(1),credentialBytes-1,credentialBytes+1}){f.disk.assign(n,0);assert(c.load()==State::StorageError);}
 f.disk=original;f.readError=true;assert(c.load()==State::StorageError);f.readError=false;assert(c.load()==State::Ready);
 for(int mode=0;mode<3;++mode){f.disk=original;assert(c.load()==State::Ready);f.writeError=mode==0;f.uncertain=mode==1;f.corruptReadback=mode==2;assert(!c.save(other,sizeof(other)-1));assert(c.state()==State::StorageError&&!c.verify(password,sizeof(password)-1));f.writeError=f.uncertain=f.corruptReadback=false;assert(c.load()==State::Ready);assert(c.verify(mode==0?password:other,mode==0?sizeof(password)-1:sizeof(other)-1));}
 f.disk=original;assert(c.load()==State::Ready);assert(c.save(other,sizeof(other)-1));assert(c.verify(other,sizeof(other)-1)&&!c.verify(password,sizeof(password)-1));assert(f.disk!=original);
}
