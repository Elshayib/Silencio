# Local-only output-only over cloud processing

All system audio stays on-machine with no network use, and only the speaker render path is processed while microphone inputs are untouched. We chose this over cloud GPU inference because uploading the full system mix would break privacy and add network delay that kills the instant budget.
