import json
from cicero_agent.classifier import classify
from cicero_agent.models import IncomingEmail

with open("tests/cicero_email_evaluation_dataset.json") as f:
    dataset = json.load(f)

correct = 0

for row in dataset:
    email = IncomingEmail(
        sender="test@example.com",
        subject="Test",
        body=row["body"],
        crm_role=row["crm_role"]
    )

    result = classify(email)

    if result.intent == row["expected_intent"]:
        correct += 1

print(f"Accuracy: {correct/len(dataset):.2%}")