import sys

with open('report_generator.py', 'r', encoding='utf-8') as f:
    content = f.read()

start_sig = "    fallback_conclusions = {"
end_sig = "        }\n    }\n\n    lang_key = 'hi' if language == 'hi' else 'en'"

start_idx = content.find(start_sig)
end_idx = content.find(end_sig, start_idx) + 14

if start_idx == -1 or end_idx == -1 + 14:
    print('Could not find fallback_conclusions block.')
    sys.exit(1)

correct_block = """    fallback_conclusions = {
        'en': {
            'pca': {
                'peaked_drop': "Crop showed strong early vigor but later declined, indicating onset of stress.",
                'declining': "Crop conditions steadily declined over the period, suggesting persistent field-level stress.",
                'improving': "Crop health consistently improved, reflecting robust plant development and resilience.",
                'stable': "Crop conditions remained relatively stable and normal throughout the observed period.",
                'low': "Crop vigor remained persistently low throughout the period, suggesting underlying stress conditions."
            },
            'chlorophyll': {
                'peaked_drop': "Leaf greenness was strong initially but faded steadily as the crop matured.",
                'declining': "Crop greenness steadily dropped, suggesting possible nutrient deficiency or onset of senescence.",
                'improving': "Crop greenness increased steadily, indicating good nutrition and healthy development.",
                'stable': "Crop greenness remained stable and normal throughout the observed period.",
                'low': "Leaf greenness stayed persistently low, indicating suboptimal photosynthetic activity."
            },
            'lai': {
                'peaked_drop': "Crop canopy expansion was excellent initially but dropped off sharply later.",
                'declining': "Leaf area and canopy expansion declined steadily, leading to a progressively thinning crop.",
                'improving': "Canopy expansion steadily increased, resulting in good vegetation density across the field.",
                'stable': "Crop canopy coverage in the field remained consistent and stable throughout the period.",
                'low': "Canopy expansion was consistently low, leaving the field with sparse vegetation throughout."
            },
            'soilmoisture': {
                'peaked_drop': "Soil moisture was adequate initially but dropped significantly, resulting in late-season dry conditions and stress.",
                'declining': "Soil moisture levels declined steadily throughout the period, resulting in prolonged moisture stress across the field.",
                'improving': "Soil moisture levels improved and remained well-replenished, providing favorable moisture conditions for crop development.",
                'stable': "Soil moisture remained stable and adequate, supporting steady crop water requirements throughout the period.",
                'low': "Soil moisture stayed critically low throughout the period, indicating severe and continuous water stress."
            }
        },
        'hi': {
            'pca': {
                'peaked_drop': "फसल में शुरुआत में अच्छी वृद्धि दिखी, लेकिन बाद में गिरावट और तनाव दर्ज किया गया।",
                'declining': "पूरे समय फसल की स्थिति में लगातार गिरावट देखी गई, जिससे खेत में तनाव का पता चलता है।",
                'improving': "फसल के स्वास्थ्य में निरंतर सुधार हुआ और पौधे मजबूत व स्वस्थ बने रहे।",
                'stable': "पूरी अवधि के दौरान फसल की स्थिति स्थिर और सामान्य बनी रही।",
                'low': "पूरी अवधि में फसल की स्थिति कमजोर और तनावग्रस्त बनी रही।"
            },
            'chlorophyll': {
                'peaked_drop': "शुरुआत में पत्तियों का हरापन अच्छा रहा, जो फसल पकने के साथ धीरे-धीरे कम हुआ।",
                'declining': "फसल के हरेपन में लगातार कमी आई, जिससे पोषक तत्वों की कमी का संकेत मिलता है।",
                'improving': "फसल में हरापन लगातार बढ़ा, जो अच्छे पोषण और स्वस्थ विकास को दर्शाता है।",
                'stable': "फसल का हरापन पूरी अवधि में स्थिर और सामान्य बना रहा।",
                'low': "पत्तियों में हरापन लगातार कम रहा, जिससे सामान्य से कम वानस्पतिक गतिविधि दिखी।"
            },
            'lai': {
                'peaked_drop': "शुरुआत में फसल का फैलाव बहुत अच्छा रहा, जो बाद में तेजी से कम हुआ।",
                'declining': "पत्तियों के फैलाव में लगातार कमी आई और फसल धीरे-धीरे हल्की होती गई।",
                'improving': "फसल का फैलाव लगातार बढ़ा और पूरे खेत में अच्छी सघनता बनी।",
                'stable': "खेत में फसल का फैलाव पूरी अवधि में एक समान और स्थिर बना रहा।",
                'low': "पूरे समय फसल का फैलाव कम और खेत में हरियाली हल्की बनी रही।"
            },
            'soilmoisture': {
                'peaked_drop': "शुरुआत में मिट्टी में नमी पर्याप्त थी, लेकिन बाद में भारी गिरावट से सूखा तनाव बना।",
                'declining': "मिट्टी की नमी में लगातार कमी आई, जिससे खेत में सूखे की स्थिति बनी।",
                'improving': "मिट्टी में नमी का स्तर सुधरा और फसल के लिए अनुकूल बना रहा।",
                'stable': "मिट्टी में पानी की मात्रा संतुलित और फसल के लिए पर्याप्त बनी रही।",
                'low': "मिट्टी में नमी की भारी कमी रही, जिससे फसल को लगातार पानी का तनाव झेलना पड़ा।"
            }
        }
    }"""

content = content[:start_idx] + correct_block + content[end_idx:]

with open('report_generator.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Replaced fallback_conclusions block successfully.')
