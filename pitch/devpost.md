## Inspiration

Private Eye grew out of Mark's research on vision-language models (VLMs): models that look at a picture and answer questions about it. We wanted to know what that is worth to someone who can't see the picture. Most assistants for blind people either upload each photo to a server or connect the user to a sighted volunteer. We wanted one that answers at once, works with no signal, and keeps everything the camera sees on the phone.

## What it does

Private Eye is an iPhone app for blind and low-vision users. You point the phone, tap, and it tells you what is in front of you, out loud and nearest things first: "Canon EOS camera with a zoom lens on the desk. Laptop behind it, to the right." Hold the screen and you can ask any question about what the camera sees, have it read a label, a sign or a screen, or ask "How far is that?" and get the distance from LiDAR.

It also remembers. Say "This is Sarah" once, and later it tells you "Sarah, 3 feet ahead." Say "Remember this as my water bottle", and from then on it points out *your* bottle among the others on the table, or tells you where and when it last saw it. And it can look for things: "Watch for my jacket" starts a 30-second search that beeps each second, then chimes and buzzes when the jacket comes into view. The search works for anything you can describe. In testing it found "a T-shirt that has code on it".

Nothing leaves the phone. There is no account and no upload, and the memory of faces and belongings is a single file on the device.

## How we built it

The app is written in Swift for the iPhone 17 Pro and uses the camera and LiDAR. The language model is LFM3-VL-2B, a 2-billion-parameter VLM, quantized to 4 bits and run on the phone with llama.cpp. It loads in about a second, reads a frame in about 0.7 seconds and speaks at 40 to 50 tokens a second. Around it sit YOLOE for detection and segmentation, two embedding models for memory (ArcFace for faces, DINOv3 for belongings), and on-device text recognition, speech recognition and voice.

The model on the phone is Witness-2B, our own fine-tune of LFM3, and we built it on Databricks. We started from VizWiz, 20,000 photos taken by blind people, each with the question they asked. gpt-6.1-sol rewrote every label from the photo through the Databricks AI Gateway, which cost $87. The labels, photos, grades and model versions live in Unity Catalog. Training was two LoRA runs on a single GPU, 13 and 25 minutes. One Databricks Job grades any model on 500 held-out photos, with the runs tracked in MLflow and an AI/BI dashboard and Genie on top.

## Challenges we ran into

We had a working app by the first evening, and in our own testing it did fairly well. Then we ran it on 500 real photos from blind users and found that small models make things up. Asked "What is my blood pressure reading?" over a display washed out by glare, it answered "125/80". On photos that could not answer the question at all, it invented an answer 58% of the time.

So we dug into the data, and the data turned out to be the problem. Blind users can't check the shot, so 31% of the photos can't fully answer their question: they are blurry, dark, or the thing is out of frame. For 20% the photo gives no answer at all. The crowd-written labels were noisy too. Our relabelling overturned 14% of them and refined another 37%.

The first fine-tune then fixed one thing and broke another. It cut invented answers from 58% to 9%, but it also refused 71 photos it could have answered, and its scene descriptions lost their sense of position, because the dataset has questions but no "what is in front of me" taps. For the second run we added 19,400 examples of what the app actually asks: describing the scene on a tap, saying where a thing is, picking one out of several, and saying when a thing isn't in view. The photos came from COCO, VizWiz and our own phone frames. We also rewrote all 6,400 refusals to say what to do next. That doubled the training set to 40,000 examples.

The last challenge was the users themselves. We reached out to blind people for testing and nobody replied in time, so we stood in for them. That is not a substitute, but it did lead us to shorten the descriptions and to add the search.

## Accomplishments that we're proud of

We are proudest of Witness-2B. On photos that can't answer the question it invents an answer 8% of the time. The six other 2B models we tested, stock LFM3 included, invent one 57% to 80% of the time, so Witness-2B hallucinates seven times less than the next best. It is also the most accurate of the seven overall, with under half the errors of any rival: 13% of its answers are wrong, against 31% to 39%.

And when it can't see, it says what to do. For the blood pressure photo it replies "Glare obscures the reading. Tilt the phone." All of this runs with no network, with the first words arriving about a quarter of a second after you stop speaking. We took the whole pipeline, from relabelling to a graded model on the phone, through inside a 24-hour hackathon.

## What we learned

The biggest gain came from fixing the data. Clean labels did more than any prompt we wrote. We also learned that fine-tuning changes what you don't measure: our first run looked better on the benchmark and worse in the hand, so we now grade every kind of request the app makes.

We learned that a refusal has to be useful. "Can't tell" helps nobody; "Turn the box over" does. And on a phone you can't buy accuracy with a bigger model. A small model with the right data beat every other model its size.

## What's next for Private Eye

Testing with blind users comes first. After that we want to move the camera to smart glasses so both hands stay free, keep training on the cases the model still gets wrong, and use LiDAR to map indoor spaces so the app can find a path through a building. Obstacle haptics are already in the app, switched off until they are tuned.
