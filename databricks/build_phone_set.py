"""Phone-frame test set: 42 turns saved by the app on 2026-11-14 where the model answered a spoken question.

Reference labels were written by Claude from the saved frames (720x960), not by a crowd or an API:
the frames show people and stay on this machine. Junk transcripts, repeated frames and ID-card
questions were left out. Usage: python3 -I build_phone_set.py <turns dir> <out dir>
"""
import json, os, shutil, sys

turns_dir, out_dir = sys.argv[1:3]
LABEL_SUFFIX = ('Answer in a short, specific phrase. If it has a label or brand, read it, like '
                '"Shampoo bottle, Head and Shoulders." If you cannot tell, say "Can\'t tell."')
# (turn id, question as heard, answerable, reference answer, acceptable answers, answer type)
ROWS = [
    ("145343-588", "What is in front of me?", "yes", "A person in a black T-shirt sitting close, facing left.", ["A person", "Someone sitting in front of you", "A man in a black T-shirt"], "description"),
    ("150336-496", "What is this?", "yes", "A can of Red Bull energy drink.", ["Red Bull can", "Red Bull", "Red Bull energy drink, 8.4 ounces"], "object_identity"),
    ("150343-092", "What is this?", "yes", "A Red Bull energy drink can, turned to its nutrition facts.", ["Energy drink can", "Red Bull can", "A drink can showing nutrition facts"], "object_identity"),
    ("150354-700", "What is this describe in detail?", "yes", "A slim 8.4 ounce drink can, nutrition label facing you, on a wooden table.", ["An energy drink can showing its nutrition facts", "A drink can on a table with a laptop behind it", "Red Bull can"], "description"),
    ("151248-192", "What is this?", "yes", "A phone in a black case on a table, next to a laptop.", ["Phone on table", "A smartphone", "A table with a phone, laptop, ball and keychains"], "object_identity"),
    ("151854-968", "Can you tell me what this item is?", "yes", "A pink can of strawberry lemon soda.", ["Strawberry lemon drink can", "Poppi strawberry lemon soda", "A pink and yellow can labelled Strawberry Lemon"], "object_identity"),
    ("151935-507", "What is this?", "yes", "A bag of SkinnyPop original popcorn.", ["Bag of popcorn", "SkinnyPop popcorn", "Popcorn"], "object_identity"),
    ("151939-548", "What is this?", "yes", "A Canon camera, with a bag of SkinnyPop popcorn behind it.", ["Camera", "Canon camera", "A camera and a bag of popcorn"], "object_identity"),
    ("152005-834", "What is this?", "yes", "A can of Red Bull energy drink.", ["Energy drink can", "Red Bull can", "Blue and silver drink can"], "object_identity"),
    ("152014-356", "What is this?", "yes", "The back of a pink drink can, showing its barcode.", ["Pink can", "Pink soda can", "A pink drink can"], "object_identity"),
    ("155415-718", "What is this?", "yes", "A large wooden table with chairs around it.", ["Wooden table", "A conference table", "Table"], "object_identity"),
    ("155432-119", "What is this?", "yes", "An orange chair at a round white table.", ["Chair", "A chair and a table", "Chairs and a round table"], "object_identity"),
    ("155438-958", "What is this?", "yes", "Water fountains, with a restroom sign pointing left and a wet floor sign.", ["Water fountain", "Drinking fountains", "Restroom sign pointing left", "A hallway with water fountains and a restroom sign"], "description"),
    ("155441-668", "What is this?", "yes", "A drinking fountain with a bottle filler.", ["Water fountain", "Bottle filling station", "Drinking fountain"], "object_identity"),
    ("155445-615", "How much water is in here?", "no", "", [], "other"),
    ("155457-068", "Can I throw my pizza in here?", "yes", "No, this bin is for mixed recycling.", ["No", "No, it is a recycling bin"], "yes_no"),
    ("155520-560", "Can I throw some trash in here?", "yes", "Yes, this is the trash bin.", ["Yes", "Yes, it says trash"], "yes_no"),
    ("155534-019", "What is the sign say?", "yes", "Exit.", ["EXIT", "It says exit"], "text_reading"),
    ("155545-424", "What is this?", "yes", "A wall of living plants.", ["Green wall", "Plant wall", "Vertical garden"], "object_identity"),
    ("155553-982", "What time is it?", "yes", "About 3:55.", ["3:55", "3:55 PM", "3:56"], "text_reading"),
    ("155559-876", "What time is it?", "yes", "3:55.", ["3:55 PM", "3:55 and 58 seconds", "3:56"], "text_reading"),
    ("155611-148", "What is this?", "yes", "A fire department valve cabinet on the wall.", ["Fire hose cabinet", "Fire valve cabinet", "A wall cabinet with a fire department valve"], "object_identity"),
    ("155643-106", "Which city is this?", "no", "", [], "other"),
    ("155648-392", "What is this?", "yes", "A brown leather ottoman.", ["Ottoman", "Leather stool", "Pouf", "Orange leather footstool"], "object_identity"),
    ("160709-607", "What is this?", "yes", "Emergency signs and an emergency phone beside a call button.", ["Emergency phone panel", "A 911 emergency sign", "Emergency communication station", "Call button and emergency signs"], "description"),
    ("163021-900", "What color are these?", "yes", "Blue.", ["Blue glasses", "Royal blue"], "color"),
    ("163025-885", "Are they like tinted or just clear?", "yes", "Clear.", ["They are clear", "Clear lenses"], "other"),
    ("163044-029", "Are these open or closed?", "yes", "Open.", ["They are open", "Open, the arms are unfolded"], "other"),
    ("163110-202", "What is this?", "yes", "A black insulated bottle.", ["Black bottle", "Water bottle", "Thermal cup", "Black tumbler"], "object_identity"),
    ("163113-441", "What color is it?", "yes", "Black.", ["Black bottle", "Matte black"], "color"),
    ("163116-206", "Do you know the brand?", "yes", "Owala.", ["It is an Owala bottle", "Yes, Owala"], "text_reading"),
    ("163123-431", "Do I open it with this button?", "yes", "Yes, press that button to open the lid.", ["Yes", "Yes, push the button"], "yes_no"),
    ("163130-998", "Is the inside of this like rubber or like metal?", "partly", "The lid has a rubber seal and a plastic spout.", ["Rubber", "Rubber seal", "Rubber and plastic"], "other"),
    ("163159-887", "What color is this phone?", "yes", "Black.", ["Black phone", "Dark"], "color"),
    ("163206-257", "What is on the back of this phone?", "yes", "A black leather card wallet, below the camera.", ["A card holder", "A wallet attachment", "A leather wallet and the camera"], "description"),
    ("163243-788", "What is on the back of his phone?", "yes", "A card in a wallet sleeve, below the camera.", ["A card", "A card holder with a card in it", "A wallet with a card"], "description"),
    ("163816-491", "What is this?", "yes", "A laptop.", ["Laptop computer", "MacBook", "An open laptop"], "object_identity"),
    ("164052-076", "What is this?", "yes", "A can of Red Bull Zero.", ["Red Bull Zero", "Red Bull can", "Red Bull energy drink"], "object_identity"),
    ("165010-100", "What is this?", "yes", "A bottle of Kroger purified drinking water.", ["Water bottle", "Bottle of water", "Purified drinking water"], "object_identity"),
    ("165840-396", "What is he doing?", "yes", "Drinking from a can, sitting at a table with a laptop.", ["Drinking from a can", "Drinking a soda", "Sitting and drinking"], "description"),
    ("170224-562", "What is this?", "yes", "A smartwatch on a wrist, showing 5:02.", ["Smartwatch", "Apple Watch", "Watch"], "object_identity"),
    ("173526-198", "What software is running here?", "partly", "A chat app, probably Discord.", ["Chat application", "Discord", "A messaging app"], "other"),
]

frames = os.path.join(out_dir, "phone_frames")
os.makedirs(frames, exist_ok=True)
labels = []
with open(os.path.join(out_dir, "phone_styled.tsv"), "w") as a, \
     open(os.path.join(out_dir, "phone_label.tsv"), "w") as b, \
     open(os.path.join(out_dir, "phone_plain.tsv"), "w") as c:
    for n, (tid, q, ans, ref, acc, kind) in enumerate(ROWS, 1):
        src = os.path.join(turns_dir, f"20261114-{tid}.jpg")
        dst = os.path.join(frames, f"{tid}.jpg")
        if not os.path.exists(dst):
            shutil.copyfile(src, dst)
        turn = json.load(open(src[:-4] + ".json"))
        pid = f"p{n:02d}"
        labels.append({"id": pid, "turn": tid, "question": q, "answerable": ans, "reference_answer": ref,
                       "acceptable_answers": acc, "answer_type": kind,
                       "unanswerable_reason": "not_applicable" if ans == "yes" else "not_in_frame",
                       "app_reply_on_phone": turn.get("reply", "")})
        a.write(f"{pid}\t{dst}\t{q}\n")
        b.write(f"{pid}\t{dst}\t{q}\t\t{LABEL_SUFFIX}\n")
        c.write(f"{pid}\t{dst}\t{q}\t\t\n")
json.dump(labels, open(os.path.join(out_dir, "phone_labels.json"), "w"), indent=1)
print(len(labels), "phone frames")
