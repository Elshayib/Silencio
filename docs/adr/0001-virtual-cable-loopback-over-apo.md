# Virtual-cable loopback over custom driver/APO

System-wide capture needs a virtual output set as Default Playback with WASAPI loopback capture, process, and render to real speakers. We chose VB-Cable/VoiceMeeter-style loopback chain for v1 over a custom signed driver or APO because driver signing, reboot, and per-endpoint registry would cost weeks for a prototype.
