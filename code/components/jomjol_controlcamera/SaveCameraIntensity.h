#pragma once
#include "CameraConfigEdit.h"
#include "ConfigJournal.h"

namespace SaveCameraIntensity {
enum class Status { Saved, SavedCleanupPending, InvalidConfig, FailedUnchanged, RecoveryRequired };
inline Status save(ConfigJournal::Storage& storage, const std::string& path, int percent) {
    std::string before, after;
    if (storage.read(path, before) != ConfigJournal::Read::Ok ||
        before.size() > ConfigJournal::limit || !CameraConfigEdit::intensity(before, percent, after))
        return Status::InvalidConfig;
    const auto result = ConfigJournal::commit(storage, path, before, after);
    if (result == ConfigJournal::Result::Ok) return Status::Saved;
    if (result == ConfigJournal::Result::CleanupPending) return Status::SavedCleanupPending;
    std::string current;
    if (storage.read(path, current) == ConfigJournal::Read::Ok && current == before)
        return Status::FailedUnchanged;
    return Status::RecoveryRequired;
}
}
