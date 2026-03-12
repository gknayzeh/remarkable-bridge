def sync_vault_to_remarkable(vault_path, rm_folder):
    changed = get_changed_files(vault_path)
    if not changed:
        log.info("nothing to push")
        return

    for note in changed:
        pdf = convert_md_to_pdf(note, profile="color")
        rm_path = map_vault_path_to_rm(note, rm_folder)
        rmapi.put(pdf, rm_path)
        update_sync_state(note, hash=note.hash)

    log.info(f"pushed {len(changed)} notes")

class SyncState:
    entries: dict[str, Entry]
    last_sync: datetime

    def is_stale(self, path, current_hash):
        if path not in self.entries:
            return True
        return self.entries[path].hash != current_hash
