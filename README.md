# Echo-Voice-Cloning-Soundboard WebGUI
Echo - Voice Cloning Soundboard WebGUI

Works with Call of Duty, MW3, Black Ops, Fortnite, Counterstrike 2, CSGO, Rust, and really any gyatt damn game with voice chat. 

**NB:**
assuming windows - if you're linux you're used to struggling to install stuff lol good luck mate

**Prerequisites ():**
1. Python 3 (install the latest python - just google python 3 download and install it)
2. Virtual Microphone application - I use [VB-Audio Virtual Cable](https://vb-audio.com/Cable/)
3. disable almost all audio in game except for microphone. so music, noises, etc. disable all of that because it will ruin the fun. once all disabled it will sound hella quiet. 

**How to install:**
1. a) download this whole repo as a zip file, extract to desktop
1. b.1) click **start key**, type 'cmd' and **press enter**.
1. b.2) **type** 'git clone https://github.com/corporate9601/Echo-Voice-Cloning-Soundboard/'
3. (windows) **double click the 'INSTALL.bat'** file to install python requirements
4. **done** I guess... if I forgot something, please shout at me on github ;D Thank you!

**How to use it(easy):**
1. Open **windows sound settings** (Settings -> Sound)
2. Make sure **Speakers are left as they normally are**, so playing audio out your speakers or headphones it doesn't matter.
3. **Make sure the microphone is changed!** so now, you will set this to **"Virtual Mic For Audio Relay"**
4. Double click **RUN.bat** to start the echo server webGUI
5. read the terminal to see what IP your GUI is hosted on!
6. so if you want to see it on the same computer, **open a browser** and **go to** '127.0.0.1:5000'
7. if you want to control it from your phone, while in game, simply check the terminal (black window) that opened and look for the above ip '127.0.0.1:5000' and you'll see directly above or below it, is another IP.
8. it may look like '192.168.0.20:5000' or similar, you can enter this address into your phone's browser to load the WebGUI on your phone
9. As sounds come in, they create 'Recordings'.
10. you may click 'Edit' to change the name of a recording.
11. you may click 'Favorite' to add it to favorites permanently (remove from favorites coming soon ok lol)
12. click 'Play' to play the audio both on the browser its opened on, AND in game! 

**How it works:**
It intercepts your audio output on computer, pretends it's a microphone, records it. It uses VAD (voice audio detection) to separate silence and background noises from voice samples.
So it AUTOMATICALLY will create samples. you just chill and play the game. load it on your phone. someone says something that's PERFECT for a clip?
well consider it already clipped! this program will clip it in less than 1 second after they said it, and tries to transcribe it too.

PS it can be REAL quiet with all noises off, so to get people going go online to any random sound effect site search like "anyone got mic sound effect" and find one. play it and my tool will automatically clip it and add to recordings. now you can favorite the sample and use it in every game.
Having more samples gets people talking

**TROUBLESHOOTING:**
 - if you have issues with other people hearing you, make sure you set the virtual microphone correctly and don't have any other weird clashign audio things installed lol. if you have errors please feel free to reach out I love to problem solve 


**If you have any feature requests please also say so! :D **I want to make this as annoying as humanly possible. 
