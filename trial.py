from typing import Dict, Any
import pprint

pp = pprint.PrettyPrinter(indent=4)



person: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]] = {
    "apple": {
        "misc": {
            "bruv": {
                "greetings": "earthling"
            }
        },
        "attributes": {
            "pricing": {
                "price": 1.5,
                "currency": "USD"
            },
            "details": {
                "color": "red",
                "weight": "200g"
            }
        }        
    },
    "banana": {
        "attributes": {
            "pricing": {
                "price": 0.75,
                "currency": "USD"
            },
            "details": {
                "color": "yellow",
                "weight": "120g"
            }
        }
    }
}



for key1, dict_level2 in person.items():
    print("Level 1:", key1)

    for key2, dict_level3 in dict_level2.items():
        print("  Level 2:", key2)

        for key3, dict_level4 in dict_level3.items():
            print("    Level 3:", key3)

            wow = dict_level4.get("greetings")

            print("    Level Wow:", wow)

            for key4, value in dict_level4.items():
                print("      Level 4:", key4, "=", value)


print("\n\n")
pp = pprint.PrettyPrinter(indent=4)
pp.pprint(person)