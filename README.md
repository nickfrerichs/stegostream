# Stegostream
Connect and send data between two parties sharing live video streams. This is an early attempt at the concept of using video steganography as a medium to make a live connection between two peers.

This is just experimenting with an idea, not intended to be useful.

#### Working
- Data link via YouTube live streams by both peers
  - Transfers binary data encoded by an stego encoder, currently a basic RGB grid with no cover image
- Basics of a "TCP-like" connection
  - Three way handshake
  - Sequence numbers with receive buffer
