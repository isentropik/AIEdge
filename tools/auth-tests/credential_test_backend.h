#pragma once
#include "WebsiteCredential.h"
#include <array>
#include <cassert>
#include <vector>
#include <algorithm>
using namespace AIEdgeAuth;
// Deterministic fault-injection backend. Cryptography is tested separately.
struct Fake : Backend {
 std::vector<uint8_t> disk; bool readError=false,writeError=false,uncertain=false,corruptReadback=false,randomError=false,deriveError=false,digestError=false;unsigned salt=0;int writes=0;
 ReadResult read(uint8_t*r,size_t n) override {if(readError)return ReadResult::Error;if(disk.empty())return ReadResult::Missing;if(disk.size()!=n)return ReadResult::Error;std::copy(disk.begin(),disk.end(),r);if(corruptReadback)r[25]^=1;return ReadResult::Present;}
 bool write(const uint8_t*r,size_t n) override {++writes;if(writeError)return false;disk.assign(r,r+n);return !uncertain;}
 bool random(uint8_t*r,size_t n) override {if(randomError)return false;for(size_t i=0;i<n;++i)r[i]=++salt;return true;}
 bool derive(const uint8_t*p,size_t n,const uint8_t*s,uint8_t*r) override {if(deriveError)return false;for(size_t i=0;i<32;++i)r[i]=p[i%n]^s[i%16];return true;}
 bool digest(const uint8_t*p,size_t n,uint8_t*r) override {if(digestError)return false;std::fill(r,r+32,0);for(size_t i=0;i<n;++i)r[i%32]^=p[i];return true;}
};
const uint8_t password[]="a-test-password-1";const uint8_t other[]="another-password";
