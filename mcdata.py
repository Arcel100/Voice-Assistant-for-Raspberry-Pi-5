"""Minecraft (Java Edition) vocabulary for dictate.py. Safe to edit: add or remove words freely."""
import re

# every Java Edition command name
MC_COMMANDS = ("advancement attribute ban ban-ip banlist bossbar clear clone damage data datapack debug "
               "defaultgamemode deop difficulty effect enchant execute experience xp fill fillbiome forceload "
               "function gamemode gamerule give help item jfr kick kill list locate loot me msg op pardon "
               "pardon-ip particle perf place playsound publish random recipe reload return ride rotate "
               "save-all save-off save-on say schedule scoreboard seed setblock setidletimeout setworldspawn "
               "spawnpoint spectate spreadplayers stop stopsound summon tag team teammsg teleport tell tellraw "
               "tick time title tm tp transfer trigger w weather whitelist worldborder").split()

# commands whose arguments are plain chat text (kept exactly as you said them)
MC_FREE_TEXT = {"say", "me", "msg", "tell", "w", "teammsg", "tm"}

# typed into chat but NOT sent automatically, so a mishearing can't stop or ban anything
MC_DANGEROUS = {"stop", "ban", "ban-ip", "kick", "op", "deop", "pardon", "pardon-ip",
                "save-off", "setidletimeout"}

# subcommand / option words used inside commands
MC_KEYWORDS = set(("set add remove query give clear get merge modify append prepend insert value from string run "
                   "as at in on positioned align anchored facing rotated eyes feet if unless store result success "
                   "block blocks entity storage biome loaded dimension predicate score data items objectives "
                   "players list reset enable disable operation join leave empty team displayname color prefix "
                   "suffix title subtitle actionbar times center damage warning distance buffer amount points "
                   "levels creative survival adventure spectator day night noon midnight daytime gametime rain "
                   "thunder peaceful easy normal hard replace destroy keep hollow outline masked filtered force "
                   "move all only true false base grant revoke everything until through max visible style name "
                   "progress notched solid rate freeze unfreeze step sprint structure poi feature jigsaw "
                   "template with mainhand offhand spawn trace dump nearest random").split())

GAMERULE_NAMES = ("announceAdvancements blockExplosionDropDecay commandBlockOutput commandModificationBlockLimit "
                  "disableElytraMovementCheck disableRaids doDaylightCycle doEntityDrops doFireTick "
                  "doImmediateRespawn doInsomnia doLimitedCrafting doMobLoot doMobSpawning doPatrolSpawning "
                  "doTileDrops doTraderSpawning doVinesSpread doWardenSpawning doWeatherCycle drowningDamage "
                  "enderPearlsVanishOnDeath fallDamage fireDamage forgiveDeadPlayers freezeDamage "
                  "globalSoundEvents keepInventory lavaSourceConversion logAdminCommands maxCommandChainLength "
                  "maxCommandForkCount maxEntityCramming mobExplosionDropDecay mobGriefing naturalRegeneration "
                  "playersNetherPortalCreativeDelay playersNetherPortalDefaultDelay playersSleepingPercentage "
                  "projectilesCanBreakBlocks randomTickSpeed reducedDebugInfo sendCommandFeedback "
                  "showDeathMessages snowAccumulationHeight spawnChunkRadius spawnRadius "
                  "spectatorsGenerateChunks tntExplodes tntExplosionDropDecay universalAnger "
                  "waterSourceConversion").split()

def gamerule_phrases():
    """'keep inventory' -> keepInventory, 'daylight cycle' -> doDaylightCycle, ..."""
    out = {}
    for name in GAMERULE_NAMES:
        phrase = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name).lower()
        out[phrase] = name
        if phrase.startswith("do "):
            out.setdefault(phrase[3:], name)
    return out

MC_PROMPT = ("Minecraft. slash gamemode creative. slash give @s diamond_sword 1. slash tp @s ~ ~ ~. "
             "slash time set day. slash weather clear. slash effect give @s night_vision. "
             "slash gamerule keepInventory true. slash summon creeper. slash setblock. slash fill. "
             "slash enchant. slash locate. slash execute. Nether, Enderman, redstone, netherite, "
             "obsidian, elytra, shulker, Wither.")

ENTITY_IDS = ("allay area_effect_cloud armadillo armor_stand arrow axolotl bat bee blaze block_display boat bogged "
              "breeze camel cat cave_spider chest_boat chest_minecart chicken cod command_block_minecart cow "
              "creaking creeper dolphin donkey dragon_fireball drowned egg elder_guardian end_crystal "
              "ender_dragon ender_pearl enderman endermite evoker evoker_fangs experience_bottle experience_orb "
              "eye_of_ender falling_block fireball firework_rocket fishing_bobber fox frog furnace_minecart "
              "ghast giant glow_item_frame glow_squid goat guardian hoglin hopper_minecart horse husk illusioner "
              "interaction iron_golem item item_display item_frame leash_knot lightning_bolt llama llama_spit "
              "magma_cube marker minecart mooshroom mule ocelot painting panda parrot phantom pig piglin "
              "piglin_brute pillager polar_bear potion pufferfish rabbit ravager salmon sheep shulker "
              "shulker_bullet silverfish skeleton skeleton_horse slime small_fireball sniffer snow_golem "
              "snowball spawner_minecart spectral_arrow spider squid stray strider tadpole text_display tnt "
              "tnt_minecart trader_llama trident tropical_fish turtle vex villager vindicator wandering_trader "
              "warden wind_charge witch wither wither_skeleton wither_skull wolf zoglin zombie zombie_horse "
              "zombie_villager zombified_piglin player").split()

EFFECTS = ("speed slowness haste mining_fatigue strength instant_health instant_damage jump_boost nausea "
           "regeneration resistance fire_resistance water_breathing invisibility blindness night_vision hunger "
           "weakness poison wither health_boost absorption saturation glowing levitation luck unluck bad_luck "
           "slow_falling conduit_power dolphins_grace bad_omen hero_of_the_village darkness trial_omen "
           "raid_omen wind_charged weaving oozing infested")

ENCHANTS = ("protection fire_protection feather_falling blast_protection projectile_protection respiration "
            "aqua_affinity thorns depth_strider frost_walker binding_curse soul_speed swift_sneak sharpness "
            "smite bane_of_arthropods knockback fire_aspect looting sweeping_edge efficiency silk_touch "
            "unbreaking fortune power punch flame infinity luck_of_the_sea lure loyalty impaling riptide "
            "channeling multishot quick_charge piercing density breach wind_burst mending vanishing_curse")

BIOMES = ("plains sunflower_plains snowy_plains ice_spikes desert swamp mangrove_swamp forest flower_forest "
          "birch_forest dark_forest old_growth_birch_forest old_growth_pine_taiga old_growth_spruce_taiga taiga "
          "snowy_taiga savanna savanna_plateau windswept_hills windswept_gravelly_hills windswept_forest "
          "windswept_savanna jungle sparse_jungle bamboo_jungle badlands eroded_badlands wooded_badlands "
          "meadow cherry_grove grove snowy_slopes frozen_peaks jagged_peaks stony_peaks river frozen_river "
          "beach snowy_beach stony_shore warm_ocean lukewarm_ocean deep_lukewarm_ocean ocean deep_ocean "
          "cold_ocean deep_cold_ocean frozen_ocean deep_frozen_ocean mushroom_fields dripstone_caves "
          "lush_caves deep_dark nether_wastes warped_forest crimson_forest soul_sand_valley basalt_deltas "
          "the_end small_end_islands end_midlands end_highlands end_barrens the_void pale_garden")

STRUCTURES = ("village stronghold mineshaft desert_pyramid jungle_pyramid igloo ocean_monument mansion "
              "woodland_mansion pillager_outpost ruined_portal shipwreck ocean_ruin buried_treasure swamp_hut "
              "fortress nether_fortress bastion_remnant end_city ancient_city trail_ruins trial_chambers")

# items and blocks that don't come from the families further down
MISC = """
stick string feather flint gunpowder bone bone_meal leather rabbit_hide rabbit_foot scute turtle_scute
armadillo_scute paper book writable_book written_book enchanted_book map filled_map clay_ball brick nether_brick
slime_ball ender_pearl ender_eye eye_of_ender blaze_rod blaze_powder ghast_tear nether_star nether_wart
glowstone_dust redstone sugar egg wheat wheat_seeds pumpkin_seeds melon_seeds beetroot_seeds torchflower_seeds
pitcher_pod carrot potato poisonous_potato baked_potato beetroot beetroot_soup apple golden_apple
enchanted_golden_apple bread cookie cake pumpkin_pie melon_slice sweet_berries glow_berries dried_kelp
honey_bottle honeycomb mushroom_stew rabbit_stew suspicious_stew milk_bucket cod salmon tropical_fish pufferfish
cooked_cod cooked_salmon beef cooked_beef porkchop cooked_porkchop chicken cooked_chicken mutton cooked_mutton
rabbit cooked_rabbit rotten_flesh spider_eye fermented_spider_eye golden_carrot glistering_melon_slice
chorus_fruit popped_chorus_fruit magma_cream phantom_membrane prismarine_shard prismarine_crystals nautilus_shell
heart_of_the_sea shulker_shell dragon_breath dragon_egg dragon_head wither_skeleton_skull skeleton_skull
zombie_head creeper_head player_head piglin_head totem_of_undying elytra trident crossbow bow arrow
spectral_arrow tipped_arrow shield fishing_rod carrot_on_a_stick warped_fungus_on_a_stick flint_and_steel shears
brush spyglass compass recovery_compass clock lead name_tag saddle firework_rocket firework_star bundle
bucket water_bucket lava_bucket powder_snow_bucket cod_bucket salmon_bucket pufferfish_bucket
tropical_fish_bucket axolotl_bucket tadpole_bucket potion splash_potion lingering_potion experience_bottle
glass_bottle dragon_breath ominous_bottle mace wind_charge breeze_rod trial_key ominous_trial_key
coal charcoal diamond emerald lapis_lazuli quartz amethyst_shard copper_ingot iron_ingot gold_ingot
netherite_ingot netherite_scrap raw_iron raw_copper raw_gold iron_nugget gold_nugget
netherite_upgrade_smithing_template echo_shard disc_fragment_5 goat_horn painting item_frame glow_item_frame
armor_stand end_crystal minecart chest_minecart furnace_minecart hopper_minecart tnt_minecart
command_block_minecart rail powered_rail detector_rail activator_rail
crafting_table furnace blast_furnace smoker chest trapped_chest ender_chest barrel hopper dropper dispenser
observer piston sticky_piston tnt torch soul_torch redstone_torch lantern soul_lantern campfire soul_campfire
beacon conduit anvil chipped_anvil damaged_anvil enchanting_table brewing_stand cauldron lectern loom grindstone
stonecutter smithing_table cartography_table fletching_table composter bell jukebox note_block ladder scaffolding
glass glass_pane tinted_glass ice packed_ice blue_ice snow snow_block powder_snow sand red_sand gravel dirt
coarse_dirt rooted_dirt grass_block dirt_path farmland podzol mycelium moss_block moss_carpet netherrack
soul_sand soul_soil magma_block glowstone shroomlight sea_lantern slime_block honey_block hay_block bone_block
sponge wet_sponge cobweb vine glow_lichen lily_pad cactus sugar_cane bamboo kelp seagrass pumpkin
carved_pumpkin jack_o_lantern melon brown_mushroom red_mushroom mushroom_stem brown_mushroom_block
red_mushroom_block crimson_fungus warped_fungus crimson_roots warped_roots nether_sprouts weeping_vines
twisting_vines fern large_fern grass short_grass tall_grass dead_bush azalea flowering_azalea spore_blossom
big_dripleaf small_dripleaf hanging_roots amethyst_block budding_amethyst amethyst_cluster copper_block
cut_copper lightning_rod repeater comparator redstone_lamp redstone_block lever tripwire_hook tripwire
daylight_detector target sculk sculk_sensor calibrated_sculk_sensor sculk_shrieker sculk_catalyst sculk_vein
command_block chain_command_block repeating_command_block structure_block structure_void jigsaw barrier light
spawner trial_spawner vault end_portal_frame end_portal end_gateway nether_portal bedrock obsidian
crying_obsidian respawn_anchor lodestone ancient_debris reinforced_deepslate crafter decorated_pot
suspicious_sand suspicious_gravel heavy_core dandelion poppy blue_orchid allium azure_bluet red_tulip
orange_tulip white_tulip pink_tulip oxeye_daisy cornflower lily_of_the_valley wither_rose sunflower lilac
rose_bush peony torchflower pitcher_plant pink_petals leaf_litter wildflowers cactus_flower firefly_bush
music_disc_13 music_disc_cat music_disc_blocks music_disc_chirp music_disc_far music_disc_mall
music_disc_mellohi music_disc_stal music_disc_strad music_disc_ward music_disc_11 music_disc_wait
music_disc_pigstep music_disc_otherside music_disc_5 music_disc_relic music_disc_creator
music_disc_creator_music_box music_disc_precipice
stone cobblestone mossy_cobblestone smooth_stone andesite diorite granite deepslate cobbled_deepslate
polished_deepslate deepslate_bricks deepslate_tiles blackstone polished_blackstone nether_bricks
red_nether_bricks chiseled_stone_bricks cracked_stone_bricks mossy_stone_bricks stone_bricks quartz_block
smooth_quartz quartz_pillar chiseled_quartz_block sandstone red_sandstone chiseled_sandstone cut_sandstone
prismarine prismarine_bricks dark_prismarine purpur_block purpur_pillar end_stone end_stone_bricks bricks
mud_bricks packed_mud mud clay terracotta tuff calcite dripstone_block pointed_dripstone basalt smooth_basalt
raw_iron_block raw_copper_block raw_gold_block gilded_blackstone chiseled_deepslate chiseled_nether_bricks
oak_planks bookshelf chiseled_bookshelf hay_bale white_wool sniffer_egg turtle_egg frogspawn
"""

WOODS = "oak spruce birch jungle acacia dark_oak mangrove cherry bamboo crimson warped pale_oak".split()
WOOD_PARTS = ("planks log wood stripped_log stripped_wood stairs slab fence fence_gate door trapdoor button "
              "pressure_plate sign hanging_sign boat chest_boat leaves sapling mosaic block").split()
COLORS = ("white orange magenta light_blue yellow lime pink gray light_gray cyan purple blue brown green "
          "red black").split()
COLOR_PARTS = ("wool carpet concrete concrete_powder terracotta glazed_terracotta stained_glass "
               "stained_glass_pane bed banner shulker_box candle dye bundle").split()
TOOL_MATS = "wooden stone iron golden diamond netherite".split()
TOOLS = "sword pickaxe axe shovel hoe".split()
ARMOR_MATS = "leather chainmail iron golden diamond netherite turtle".split()
ARMOR = "helmet chestplate leggings boots".split()
STONES = ("stone cobblestone mossy_cobblestone stone_brick mossy_stone_brick smooth_stone andesite diorite granite "
          "polished_andesite polished_diorite polished_granite cobbled_deepslate polished_deepslate "
          "deepslate_brick deepslate_tile blackstone polished_blackstone polished_blackstone_brick nether_brick "
          "red_nether_brick quartz smooth_quartz sandstone cut_sandstone smooth_sandstone red_sandstone "
          "cut_red_sandstone smooth_red_sandstone prismarine prismarine_brick dark_prismarine purpur "
          "end_stone_brick brick mud_brick tuff polished_tuff tuff_brick cut_copper exposed_cut_copper "
          "weathered_cut_copper oxidized_cut_copper").split()
METALS = "coal iron copper gold diamond emerald lapis redstone netherite".split()
CORALS = "tube brain bubble fire horn".split()

def build_ids(extra=()):
    """Every item/block/mob/effect/enchantment/biome/structure name, plus any extra words you taught it."""
    ids = set()
    ids.update(ENTITY_IDS)
    for text in (EFFECTS, ENCHANTS, BIOMES, STRUCTURES, MISC):
        ids.update(text.split())
    ids.update(f"{m}_spawn_egg" for m in ENTITY_IDS)
    for m in TOOL_MATS:
        ids.update(f"{m}_{t}" for t in TOOLS)
    for m in ARMOR_MATS:
        ids.update(f"{m}_{a}" for a in ARMOR)
    ids.update(f"{m}_horse_armor" for m in ("leather", "iron", "golden", "diamond"))
    for w in WOODS:
        ids.update(f"{w}_{p}" for p in WOOD_PARTS)
    for c in COLORS:
        ids.update(f"{c}_{p}" for p in COLOR_PARTS)
    for s in STONES:
        ids.update(f"{s}_{p}" for p in ("stairs", "slab", "wall"))
    for m in METALS:
        ids.update([f"{m}_ore", f"deepslate_{m}_ore", f"{m}_block", f"raw_{m}", f"raw_{m}_block",
                    f"{m}_ingot", f"{m}_nugget"])
    for c in CORALS:
        ids.update([f"{c}_coral", f"{c}_coral_block", f"{c}_coral_fan", f"{c}_coral_wall_fan",
                    f"dead_{c}_coral", f"dead_{c}_coral_block", f"dead_{c}_coral_fan"])
    ids.update(x.strip().lower().replace(" ", "_") for x in extra if x and x.strip())
    return ids
