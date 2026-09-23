#pragma once
#include "WebsiteCredential.h"
namespace AIEdgeAuth {
enum class Access { Allowed, SetupRequired, Unauthorized, RetryLater, StorageError };
class WebsiteAccess {
    Backend& backend;
    Credential credential;
    uint8_t setupToken[32] = {}, cached[32] = {};
    bool tokenReady = false, cachedReady = false;
    uint64_t nextAttempt = 0;
public:
    explicit WebsiteAccess(Backend& b) : backend(b), credential(b) {}
    ~WebsiteAccess() { wipe(setupToken,sizeof setupToken); wipe(cached,sizeof cached); }
    WebsiteAccess(const WebsiteAccess&) = delete;
    WebsiteAccess& operator=(const WebsiteAccess&) = delete;
    State state() const { return credential.state(); }
    bool setupAvailable() const { return state()==State::NeedsSetup && tokenReady; }
    // Called after radio initialization; setup token is delivered over USB only.
    State initialize(uint8_t* localToken) {
        tokenReady=cachedReady=false;nextAttempt=0;
        if(localToken)wipe(localToken,sizeof setupToken);
        wipe(setupToken,sizeof setupToken);wipe(cached,sizeof cached);
        const auto s=credential.load();
        if(s==State::NeedsSetup){
            tokenReady=backend.random(setupToken,sizeof setupToken);
            if(tokenReady&&localToken)std::memcpy(localToken,setupToken,sizeof setupToken);
        }
        return s;
    }
    Access check(const uint8_t* password,size_t size,uint64_t now) {
        if(state()==State::NeedsSetup)return Access::SetupRequired;
        if(state()!=State::Ready)return Access::StorageError;
        if(!password||!size||size>128)return Access::Unauthorized;
        uint8_t fingerprint[32]={};
        if(!backend.digest(password,size,fingerprint))return Access::StorageError;
        const bool hit=cachedReady&&equal(cached,fingerprint,sizeof cached);
        if(hit){wipe(fingerprint,sizeof fingerprint);return Access::Allowed;}
        if(now<nextAttempt){wipe(fingerprint,sizeof fingerprint);return Access::RetryLater;}
        const bool verified=credential.verify(password,size);
        if(verified){std::memcpy(cached,fingerprint,sizeof cached);cachedReady=true;}
        else nextAttempt=now+1000000; // Bound costly password guesses, without delaying valid cached requests.
        wipe(fingerprint,sizeof fingerprint);
        return verified?Access::Allowed:Access::Unauthorized;
    }
    bool setup(const uint8_t* token,size_t tokenSize,const uint8_t* password,size_t size){
        if(state()!=State::NeedsSetup||!tokenReady||!token||tokenSize!=sizeof setupToken||
           !equal(token,setupToken,sizeof setupToken))return false;
        const bool saved=credential.save(password,size);
        if(saved||state()==State::StorageError){tokenReady=false;wipe(setupToken,sizeof setupToken);}
        return saved;
    }
    bool change(const uint8_t* oldPassword,size_t oldSize,const uint8_t* newPassword,size_t newSize,uint64_t now){
        if(check(oldPassword,oldSize,now)!=Access::Allowed)return false;
        const bool saved=credential.save(newPassword,newSize);
        if(saved||state()==State::StorageError){cachedReady=false;wipe(cached,sizeof cached);nextAttempt=0;}
        return saved;
    }
};
}
