#pragma once
#include "ImageArchiveTransport.h"
#include "ImageSpoolFile.h"

namespace ImageArchive {
// A queue belongs to one exact destination and device identity across boots.
// Include credentials and trust configuration: changing either must not silently
// send previously queued images under a different authorization context.
// Do not include timeouts, firmware or random boot IDs; these do not change ownership.
template<class Hash>
std::string archiveQueueKey(const Destination& destination,const std::string& device) {
    if(!validArchiveDestination(destination)||!validName(device))return "";
    std::string identity="aiedge-archive-destination-v1";
    for(const auto& field:{destination.host,std::to_string(destination.port),
                          destination.certificatePem,destination.token,device})
        identity+=":"+std::to_string(field.size())+":"+field;
    return hashBytes<Hash>(identity);
}
}
