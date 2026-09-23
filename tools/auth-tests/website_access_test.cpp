#include "credential_test_backend.h"
#include "WebsiteAccess.h"
int main(){
 Fake f;WebsiteAccess access(f);uint8_t token[32]={};
 assert(access.check(password,sizeof(password)-1,0)==Access::StorageError);
 assert(access.initialize(token)==State::NeedsSetup);
 assert(access.check(password,sizeof(password)-1,0)==Access::SetupRequired);
 uint8_t wrong[32]={};assert(!access.setup(wrong,sizeof wrong,password,sizeof(password)-1)&&f.writes==0);
 assert(!access.setup(token,31,password,sizeof(password)-1)&&f.writes==0);
 assert(!access.setup(token,32,password,1)&&f.writes==0);
 assert(access.setup(token,32,password,sizeof(password)-1));assert(access.state()==State::Ready);
 assert(!access.setup(token,32,other,sizeof(other)-1)); // Token consumed; cannot overwrite a configured device.
 assert(access.check(other,sizeof(other)-1,0)==Access::Unauthorized);
 assert(access.check(password,sizeof(password)-1,999999)==Access::RetryLater);
 assert(access.check(password,sizeof(password)-1,1000000)==Access::Allowed);
 assert(access.check(other,sizeof(other)-1,1000000)==Access::Unauthorized);
 assert(access.check(password,sizeof(password)-1,1000000)==Access::Allowed); // Cached valid user is not denied by someone else's guess.
 assert(!access.change(other,sizeof(other)-1,other,sizeof(other)-1,3000000));
 assert(access.change(password,sizeof(password)-1,other,sizeof(other)-1,3000000));
 assert(access.check(password,sizeof(password)-1,4000000)==Access::Unauthorized);
 assert(access.check(other,sizeof(other)-1,5000000)==Access::Allowed);
 assert(access.initialize(token)==State::Ready);for(auto b:token)assert(b==0);
 assert(access.check(other,sizeof(other)-1,0)==Access::Allowed);
 f.writeError=true;assert(!access.change(other,sizeof(other)-1,password,sizeof(password)-1,0));assert(access.check(other,sizeof(other)-1,0)==Access::StorageError);f.writeError=false;
 assert(access.initialize(token)==State::Ready&&access.check(other,sizeof(other)-1,0)==Access::Allowed);
 f.disk[30]^=1;assert(access.initialize(token)==State::StorageError);assert(access.check(other,sizeof(other)-1,0)==Access::StorageError);assert(!access.setup(token,32,password,sizeof(password)-1));
 Fake unavailable;unavailable.randomError=true;WebsiteAccess noToken(unavailable);assert(noToken.initialize(token)==State::NeedsSetup);assert(!noToken.setup(token,32,password,sizeof(password)-1)&&unavailable.writes==0);
 Fake failing;WebsiteAccess uncertain(failing);assert(uncertain.initialize(token)==State::NeedsSetup);failing.uncertain=true;assert(!uncertain.setup(token,32,password,sizeof(password)-1));assert(uncertain.check(password,sizeof(password)-1,0)==Access::StorageError);failing.uncertain=false;assert(uncertain.initialize(token)==State::Ready);assert(uncertain.check(password,sizeof(password)-1,0)==Access::Allowed);

 for(int mode=0;mode<6;++mode){
  Fake storage;WebsiteAccess owner(storage);uint8_t setupCode[32]={},code[16]={},bad[16]={};owner.initialize(setupCode);assert(owner.setup(setupCode,32,password,sizeof(password)-1));assert(owner.check(password,sizeof(password)-1,0)==Access::Allowed);
  assert(owner.beginLocalRecovery(100,code));
  if(mode==0){assert(!owner.confirmLocalRecovery(bad,16,101)&&storage.erases==0);assert(!owner.confirmLocalRecovery(code,16,102)&&storage.erases==0);continue;}
  if(mode==1){assert(!owner.confirmLocalRecovery(code,16,60000100)&&storage.erases==0);continue;}
  storage.eraseError=mode==2;storage.eraseUncertain=mode==3;storage.eraseNoop=mode==4;
  const bool reset=owner.confirmLocalRecovery(code,16,101);assert(storage.erases==1);assert(reset==(mode==5));assert(!owner.confirmLocalRecovery(code,16,102)&&storage.erases==1);
  assert(owner.check(password,sizeof(password)-1,102)==(reset?Access::SetupRequired:Access::StorageError));
  storage.eraseError=storage.eraseUncertain=storage.eraseNoop=false;
  if(mode==2||mode==4){assert(owner.initialize(setupCode)==State::Ready);assert(owner.check(password,sizeof(password)-1,0)==Access::Allowed);}else assert(owner.initialize(setupCode)==State::NeedsSetup);
 }
 Fake replace;WebsiteAccess replaced(replace);uint8_t first[16]={},second[16]={};assert(replaced.beginLocalRecovery(0,first));assert(replaced.beginLocalRecovery(1,second));assert(!replaced.confirmLocalRecovery(first,16,2)&&replace.erases==0);
}
