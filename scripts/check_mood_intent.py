from app.ml.clap import ClapTextEncoder
from app.ml.mood_intent import MoodIntentResolver


encoder = ClapTextEncoder()
resolver = MoodIntentResolver(encoder)

queries = [
    "I wanna rage music for gym",
    "now I feel sad",
    "I need something calm for studying",
    "play something fun for a party",
]

for query in queries:
    print(f"\nQUERY: {query}")

    predictions = resolver.resolve(query)

    for prediction in predictions:
        print(
            f"{prediction.score:.4f} | "
            f"{prediction.mood}"
        )

encoder.unload()