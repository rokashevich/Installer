# installer
![Screenshot of the program working](screenshots/20211112.png?raw=true "Installer")

Rsyncs files over lan in a "spider" mode:

Let we have 16 hosts named 0..15

Installation is complete in 4 steps:
step 1) 0               -> 1
step 2) 0,1             -> 2,3
step 3) 0,1,2,3         -> 4,5,6,7
step 4) 0,1,2,3,4,5,6,7 -> 8,9,10,11,12,13,14,15
