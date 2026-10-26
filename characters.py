"""Character presets shared by setup, image generation and Manga Studio."""
CHARACTERS = {
    'marian': {
        'name': 'マリアン：クイーン', 'trigger': 'm4r14nqu33n2',
        'repo': 'uwgm/Moss', 'file': 'mossimage_lora_marian_queen2.safetensors',
        'workflow': 'moss_marian_queen2_1152x1536_25.json',
        'description': 'An adult woman with red eyes, long silver-white hair, black bangs and dark inner hair. She wears a black crystalline spiked crown with a black bow, a violet jewel at her collar, a dark sheer bodysuit with glossy black crossed filigree panels, short pleated black hip frills, black elbow-length fingerless gloves, patterned dark tights and black heels.',
        'prompt': 'A detailed anime illustration. She stands in a ruined cathedral at dusk, one hand resting on an ancient stone railing, composed and resolute expression. Low three-quarter camera angle, flowing hair and fabric, layered broken arches, airborne dust caught in crimson backlight, precise linework, rich shadows, intricate costume details. One complete illustration, no panels, no lettering.',
    },
    'scarlet': {
        'name': '紅蓮：神殺', 'trigger': 'sc4rl3tg0d',
        'repo': 'uwgm/Moss', 'file': 'MossImage_scarlet_goddeath.safetensors',
        'workflow': 'moss_scarlet_goddeath_1152x1536_25.json',
        'description': 'An adult woman with long pale silver-lavender hair in a half updo, a hair ornament and a red ribbon. She wears a sleeveless black Japanese-inspired dress with red trim and side slits, a red scarf, long black gloves, bandages on her arm, and black tights.',
        'prompt': 'A detailed anime illustration. She stands beneath a ruined shrine gate after the rain, calm and determined, one hand near her sheathed katana. Low three-quarter camera angle, scarf and hair drifting in the wind, wet stone reflecting deep red lantern light, layered mist and distant shrine architecture, crisp linework, dramatic rim lighting, intricate original costume details. One complete illustration, no panels, no lettering.',
    },
}


def image_prompt(character_id, prompt):
    character = CHARACTERS[character_id]
    return character['trigger'] + ', ' + character['description'] + '\n' + prompt
