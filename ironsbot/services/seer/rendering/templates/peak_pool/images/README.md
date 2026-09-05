# Official Backpack Badges

These PNGs are native Sprite exports from the official Unity client. Copyright
belongs to the original game rights holders; these are not newly drawn assets.

- Package: `DefaultPackage`, version `20260904173603`.
- Bundle: `art_ui_common`, `5e6c229fb347085f7c82983e9ca67e6d`.
- Source: https://newseer.61.com/Assets/StandaloneWindows64/DefaultPackage/5e6c229fb347085f7c82983e9ca67e6d
- Extraction: UnityPy `Sprite.image`, preserving original dimensions and alpha.
- Assets under `Assets/Art/Ui/common/`:
  - `peakjihad_sports_pool_numbg.png` (44 x 49)
  - `peakjihad_sports_pool_banbg.png` (44 x 49)
  - `ban.png` (30 x 30)
  - `NewCommon/newpetbagMainPanel_shuxingdi.png` (34 x 34)

The `game_ui_petbag` prefab bundle (`38968d5d8cca013641f0ad956387dd71`)
uses a 29 x 33 restriction background, a 20 x 20 ban symbol, and a 24 x 24
attribute background containing an 18 x 18 attribute image. Restriction numbers
are Text components, not separate PNGs. Attribute images continue to be loaded
by the existing official PetType image source.

Pool cells preserve their existing layout and IDs; this reuses the badge assets
and dimensions, not the entire game UI, font renderer or backpack layout.
