import sys

with open('report_generator.py', 'r', encoding='utf-8') as f:
    content = f.read()

hindi_translation = """        "hi": {
            "logo_alt": "MapZest कृषि बुद्धिमत्ता",
            "not_specified": "निर्दिष्ट नहीं",
            "aoi_title": "रुचि का क्षेत्र (AOI)",
            "aoi_label": "AOI",
            "aoi_map_title": "AOI (उपयोगकर्ता द्वारा खींचा गया)",
            "aoi_na": "AOI प्रदान नहीं किया गया",
            "aoi_area": "AOI क्षेत्रफल (हेक्टेयर)",
            "time_period": "समय अवधि",
            "cloud_cover": "बादल आच्छादन",
            "report_generated": "रिपोर्ट तैयार की गई",
            "ndvi_title": "वनस्पति (NDVI)",
            "pca_title": "फसल स्वास्थ्य",
            "ndvi_chart_title_suffix": "समय के साथ स्वास्थ्य",
            "ndvi_na": "NDVI समय शृंखला उपलब्ध नहीं है",
            "cwr_title": "फसल जल आवश्यकता",
            "kc_title": "फसल गुणांक",
            "lst_title": "खेत का तापमान",
            "etc_title": "कुल जल हानि",
            "sm_title": "मिट्टी में नमी का बदलाव",
            "soilmoisture_title": "मिट्टी की नमी (%)",
            "soilmoisture_avg": "<b>औसत मिट्टी की नमी: {mean:.2f}%</b>",
            "soilmoisture_trend": "<b>मिट्टी की नमी का रुझान:</b> {trend}",
            "analytics_title": "समग्र फसल विश्लेषिकी (सारांश)",
            "analytics_health_na": "फसल स्वास्थ्य डेटा उपलब्ध नहीं है",
            "analytics_cwr_na": "जल आवश्यकता डेटा उपलब्ध नहीं है",
            "analytics_health": "वर्तमान चंदवा स्वास्थ्य (NDVI औसत): <b>{mean:.2f}</b>",
            "analytics_cwr": "अनुमानित जल की आवश्यकता (औसत CWR): <b>{mean:.2f} मिमी/दिन</b>",
            "analytics_temp": "खेत का औसत तापमान: <b>{mean:.2f} °C</b>",
            "analytics_sm": "औसत मिट्टी की नमी: <b>{mean:.2f}%</b>",
            "analytics_rec": "सिफारिश: इन निष्कर्षों की पुष्टि करने के लिए खेत का निरीक्षण करें और उचित कार्रवाई करें।",
            "pie_title": "खेत का आवरण: वनस्पति बनाम बंजर भूमि",
            "pie_interp": "व्याख्या: अधिक वनस्पति प्रतिशत अच्छे चंदवा आवरण या घने खरपतवार को इंगित करता है। कम प्रतिशत स्पष्ट मिट्टी, विरल वनस्पति या बहुत प्रारंभिक फसल अवस्था को दर्शाता है।",
            "pie_no_data": "कोई डेटा नहीं",
            "landcover_veg": "वनस्पति",
            "landcover_bare": "बंजर भूमि",
            "thanks": "धन्यवाद",
            "contact": "किसी भी पूछताछ के लिए, संपर्क करें: contact@terraquauav.com",
            "analysis_title": "<b>{title} — विस्तृत विश्लेषण:</b>",
            "analysis_no_data": "इस पैरामीटर के लिए एक मजबूत सारांश की गणना करने के लिए डेटा उपलब्ध नहीं है।",
            "analysis_trend_stable": "रीडिंग <b>स्थिर</b> रही है, {start:.2f} से शुरू होकर {end:.2f} के करीब समाप्त हुई है।",
            "analysis_trend_positive": "एक <b>सकारात्मक रुझान</b> देखा गया, जो {start:.2f} से बढ़कर {end:.2f} हो गया।",
            "analysis_trend_downward": "एक <b>नीचे की ओर रुझान</b> देखा गया, जो {start:.2f} से गिरकर {end:.2f} हो गया।",
            "analysis_recent_stable": "सबसे हाल की रीडिंग <b>स्थिरता</b> दिखाती है।",
            "analysis_recent_improve": "सबसे हाल की रीडिंग में <b>हालिया सुधार</b> दिखाती है।",
            "analysis_recent_decline": "सबसे हाल की रीडिंग <b>हालिया गिरावट</b> दिखाती है।",
            "analysis_note": "<b>नोट:</b> इन सिफारिशों को स्थानीय परिस्थितियों, मिट्टी के प्रकार और विशिष्ट फसल की आवश्यकताओं के आधार पर अनुकूलित किया जाना चाहिए।",
            "ndvi_avg": "<b>औसत फसल स्वास्थ्य सूचकांक: {mean:.3f}</b>",
            "ndvi_vlow": "• <b>बहुत कम स्वास्थ्य:</b> बंजर मिट्टी, तनावग्रस्त वनस्पति या फसल विफलता को दर्शाता है",
            "ndvi_low": "• <b>कम से मध्यम स्वास्थ्य:</b> शुरुआती तनाव के लक्षण या विरल वनस्पति को दर्शाता है",
            "ndvi_mod": "• <b>मध्यम स्वास्थ्य:</b> सुधार की गुंजाइश के साथ औसत फसल की स्थिति",
            "ndvi_good": "• <b>अच्छा स्वास्थ्य:</b> मजबूत प्रकाश संश्लेषक गतिविधि के साथ स्वस्थ वनस्पति",
            "ndvi_exc": "• <b>उत्कृष्ट स्वास्थ्य:</b> घनी, जोरदार वनस्पति के साथ इष्टतम फसल की स्थिति",
            "ndvi_trend": "<b>ऐतिहासिक रुझान:</b> {trend}",
            "ndvi_recent": "<b>हालिया पैटर्न:</b> {trend}",
            "cwr_avg": "<b>दैनिक जल की औसत आवश्यकता: {mean:.2f} मिमी/दिन</b>",
            "cwr_trend": "<b>जल की आवश्यकता का रुझान:</b> {trend}",
            "kc_avg": "<b>औसत फसल गुणांक (Kc): {mean:.2f}</b>",
            "kc_trend": "<b>विकास चरण का रुझान:</b> {trend}",
            "lst_avg": "<b>खेत का औसत तापमान: {mean:.1f}°C</b>",
            "lst_trend": "<b>तापमान रुझान:</b> {trend}",
            "etc_avg": "<b>औसत कुल जल हानि: {mean:.2f} मिमी/दिन</b>",
            "etc_trend": "<b>जल हानि का रुझान:</b> {trend}",
            "sm_avg": "<b>औसत दैनिक मिट्टी की नमी: {mean:.2f}%</b>",
            "sm_trend": "<b>मिट्टी की नमी का रुझान:</b> {trend}",
            "default_avg": "<b>औसत मान: {mean:.2f}.</b>",
            "default_trend": "<b>प्रवृत्ति विश्लेषण:</b> {trend}",
            "irrigation_title": "स्मार्ट सिंचाई अनुसूची",
            "irrigation_summary_title": "सिंचाई सारांश",
            "irrigation_timeline_title": "सिंचाई की समयरेखा",
            "irrigation_priority_title": "प्राथमिकता वितरण",
            "irrigation_comparison_title": "जल की आवश्यकता बनाम वर्षा की तुलना",
            "irrigation_calendar_title": "सिंचाई कैलेंडर",
            "irrigation_total_events": "कुल सिंचाई घटनाएँ",
            "irrigation_total_water": "कुल आवश्यक जल",
            "irrigation_water_saved": "जल की बचत (स्मार्ट शेड्यूलिंग)",
            "irrigation_savings_percent": "जल की बचतें",
            "irrigation_urgent": "अत्यावश्यक कार्यक्रम",
            "irrigation_high": "उच्च प्राथमिकता वाले कार्यक्रम",
            "irrigation_medium": "मध्यम प्राथमिकता वाले कार्यक्रम",
            "irrigation_date": "दिनांक",
            "irrigation_amount": "मात्रा (मिमी)",
            "irrigation_priority": "प्राथमिकता",
            "irrigation_advice": "सलाह",
            "irrigation_no_data": "कोई सिंचाई डेटा उपलब्ध नहीं है",
            "field_intel_title": "खेत बुद्धि विश्लेषण",
            "health_scale_title": "समग्र फसल स्वास्थ्य पैमाना (0-10)",
            "health_weak": "0 – 3<br/><i>कमजोर</i>",
            "health_moderate": "4 – 7<br/><i>मध्यम</i>",
            "health_strong": "8 – 10<br/><i>मजबूत</i>",
            "aoi_map_main_title": "रुचि का क्षेत्र मानचित्र",
            "aoi_map_subtitle": "खेत की सीमा दर्शाने वाला भौगोलिक संरेखित दृश्य।",
            "param_analysis_title": "विस्तृत पैरामीटर विश्लेषण",
            "map_unavailable": "मानचित्र उपलब्ध नहीं",
            "chlorophyll_na_msg": "<b>क्लोरोफिल (CLRe) मानचित्र उपलब्ध नहीं है।</b><br/>इस परत के लिए सेंटिनल-2 रेड-एज बैंड (B5/B7) की आवश्यकता है।<br/>चुनी गई समय सीमा के लिए कोई सेंटिनल-2 डेटा नहीं मिला।<br/><i>बादल रहित छवि के लिए विस्तृत समय सीमा का प्रयास करें।</i>",
            "chlorophyll_short_na": "<b>क्लोरोफिल मानचित्र अनुपलब्ध</b><br/><i>सेंटिनल-2 डेटा नहीं मिला।</i>",
        },"""

hindi_conclusions = """        'hi': {
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
        }"""

# Find the start of "hi": { in translations and replace the block
start_idx = content.find('        "hi": {')
if start_idx != -1:
    end_idx = content.find('    }', start_idx) + 5
    content = content[:start_idx] + hindi_translation + content[end_idx:]

# Find the start of 'hi': { in conclusions and replace the block
start_idx2 = content.find("        'hi': {")
if start_idx2 != -1:
    end_idx2 = content.find('        }', start_idx2) + 9
    content = content[:start_idx2] + hindi_conclusions + content[end_idx2:]

# Replace corrupted Hindi terms
content = content.replace('"Bhai Sahab", "bhai sahab", "à¤\xadà¤¾à¤ˆ à¤¸à¤¾à¤¹à¤¬", "à¤\xadà¥\x88à¤¯à¤¾", "bhaiya", "à¤•à¤¿à¤¸à¤¾à¤¨ à¤\xadà¤¾à¤ˆ", "à¤•à¤¿à¤¸à¤¾à¤¨ à¤\xadà¤¾à¤ˆ à¤¸à¤¾à¤¹à¤¬"', 
                          '"Bhai Sahab", "bhai sahab", "भाई साहब", "भैया", "bhaiya", "किसान भाई", "किसान भाई साहब"')

content = content.replace('"à¤\xadà¤¾à¤ˆ à¤¸à¤¾à¤¹à¤¬,", "à¤\xadà¤¾à¤ˆ à¤¸à¤¾à¤¹à¤¬", "à¤\xadà¥\x88à¤¯à¤¾,", "à¤\xadà¥\x88à¤¯à¤¾", "bhaiya,", "bhaiya",', 
                          '"भाई साहब,", "भाई साहब", "भैया,", "भैया", "bhaiya,", "bhaiya",')

content = content.replace('"à¤•à¤¿à¤¸à¤¾à¤¨ à¤\xadà¤¾à¤ˆ,", "à¤•à¤¿à¤¸à¤¾à¤¨ à¤\xadà¤¾à¤ˆ", "à¤•à¤¿à¤¸à¤¾à¤¨ à¤\xadà¤¾à¤ˆ à¤¸à¤¾à¤¹à¤¬,", "à¤•à¤¿à¤¸à¤¾à¤¨ à¤\xadà¤¾à¤ˆ à¤¸à¤¾à¤¹à¤¬"', 
                          '"किसान भाई,", "किसान भाई", "किसान भाई साहब,", "किसान भाई साहब"')

with open('report_generator.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Hindi text fixed.')
