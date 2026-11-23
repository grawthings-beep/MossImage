# マルチャーナ：マリンスタディをComfyUIで生成する

RunPodの **Connect → 7860 → Workflows** からどちらかを開きます。緑のプロンプト欄にトリガー `m4rc14n4m4r1ne` を残し、衣装・ポーズ・背景を書いて **Run** を押してください。

| ワークフロー | 用途 | 元画像 → 仕上げ版 |
|---|---|---|
| [MOSS_10 Fast2x](workflows/MOSS_10_Fast2x_marciana_marine_study.json) | 構図や衣装を速く試す | 864×1152 → 1728×2304 |
| [MOSS_08 Quality2x](workflows/MOSS_08_Quality2x_marciana_marine_study.json) | 全身絵や、小さく写る目元の細部を優先する | 1152×1536 → 2304×3072 |

どちらもCottonMoss Turbo INT8、マルチャーナの最終版LoRA（強度1.0）、12 steps、CFG 3、er_sde / simple、SLG layer 22（前半50%）で一度生成します。Fast版は、拡散で処理する画素数がQuality版より約44%少なくなります。生成サイズを変えると同じseedでも構図は変わります。[CottonMoss作者の設定](https://civitai.red/models/3026318/cottonmoss?modelVersionId=3437076)

## 仕上げと保存

**Runを1回**押すと、生成直後のPNGと、細かな粒を抑えて2倍に拡大したPNGの両方が保存されます。再拡散は行わず、元画像と拡大結果を混ぜて線の強さを調整します。全体に同じ処理を適用します。[2倍モデルと作例（Philip Hofmann）](https://huggingface.co/Phips/2xNomosUni_compact_otf_medium)

- 顔にざらつきが残る場合は「元画像を混ぜる割合」を初期値 **0.25** から **0.1** に下げます。肌が平らになりすぎたり、まつ毛が細くなったりしたら **0.5** に上げてください。拡大前の平滑化は「拡大前の粒状感を抑える」の半径を **0** にするとオフになります。
- 候補を続けて作るときは「仕上げ版を保存」をミュートしてRunすると、元画像だけを保存します。同じキュー内の再実行で構図を固定したいときはKSamplerのseedを固定してください。
- すでに保存した1枚を仕上げる場合は、このグラフに **Load Image** を追加してPNGを選びます。そのIMAGE出力を「拡大前の粒状感を抑える」の `image` と「元画像を混ぜる割合」の `image2` へつなぎ、「元画像を保存」をミュートしてRunします。これで生成・テキストエンコードの枝は実行対象から外れます。

PNGは `ComfyUI/output/MOSS/Marciana/Fast/` または `Quality/` に保存されます。元画像には `base_`、仕上げ版には `final_` が付くので、肌や線を同じ構図で比較できます。
