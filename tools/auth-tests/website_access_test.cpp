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
}
