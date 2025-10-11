import random
from jinja2 import Template
from copy import deepcopy

class OutcomeGenerator:
    def __init__(self, template_json):
        self.template_json = template_json
        self.static = template_json.get("static", {})
        self.dynamic = template_json.get("dynamic", {})
        self.outcomes = template_json.get("outcomes", [])

    def _weighted_choice(self, choices, key=None):
        total = sum(c["weight"] for c in choices)
        r = random.uniform(0, total)
        upto = 0
        for c in choices:
            if upto + c["weight"] >= r:
                return deepcopy(c[key]) if key else deepcopy(c)
            upto += c["weight"]
        # fallback
        return deepcopy(choices[-1][key]) if key else deepcopy(choices[-1])

    def _generate_dynamic_context(self):
        context = {}
        for key, options in self.dynamic.items():
            context[key] = deepcopy(self._weighted_choice(options, key="value"))
        return context

    def generate(self, type=None):
        if type:
            filtered = [d for d in self.outcomes if d.get("type") == type]
            outcome = self._weighted_choice(filtered)
        else:
            outcome = self._weighted_choice(self.outcomes)

        # Prepare dynamic context
        context = {
            "static": self.static,
            "dynamic": self._generate_dynamic_context()
        }

        result = deepcopy(outcome)

        for key in outcome:
            if key.endswith("Template"):
                result[key.replace("Template", "Rendered")] = Template(outcome[key]).render(context)

        return result

# Example usage:
if __name__ == "__main__":
    import json

    # Load your JSON template (replace with your actual JSON)
    with open("resources/template.json") as f:
        template_json = json.load(f)

    generator = OutcomeGenerator(template_json)

    for _ in range(3):
        print("----- Outcome -----")
        print(generator.generate())
