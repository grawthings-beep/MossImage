# マリアンとマルチャーナをComfyUIで生成する

RunPodの **Connect → 7860 → Workflows** でキャラとLoRAの版を選びます。どのワークフローにも対応するLoRAとトリガーが設定されています。緑の欄で衣装・ポーズ・背景を書いて **Run** を押してください。

| キャラLoRA | トリガー | 速く試す（864×1152 → 1728×2304） | 細部を優先（1152×1536 → 2304×3072） |
|---|---|---|---|
| マリアン：ラストアフェクション・3000ステップ版 | `m4r14nl4st2` | [Fast2x](workflows/MOSS_10_Fast2x_marian_last_affection2_3k.json) | [Quality2x](workflows/MOSS_08_Quality2x_marian_last_affection2_3k.json) |
| マルチャーナ：マリンスタディ・元の33枚版 | `m4rc14n4m4r1ne` | [Fast2x](workflows/MOSS_10_Fast2x_marciana_marine_study_original_33.json) | [Quality2x](workflows/MOSS_08_Quality2x_marciana_marine_study_original_33.json) |
| マルチャーナ：マリンスタディ・30枚版 v1 | `m4rc14n4m4r1ne` | [Fast2x](workflows/MOSS_10_Fast2x_marciana_marine_study_30_v1.json) | [Quality2x](workflows/MOSS_08_Quality2x_marciana_marine_study_30_v1.json) |

初期値はCottonMoss Turbo INT8、キャラLoRA強度1.0、12 steps、CFG 3、er_sde / simple、SLG layer 22（前半50%）です。Fast版は、拡散で処理する画素数がQuality版より約44%少なくなります。[CottonMoss作者の設定](https://civitai.red/models/3026318/cottonmoss?modelVersionId=3437076)

**生成モデルを切り替える**には、左端の「CottonMoss Turbo INT8」ノードで `moss_image_base_bf16.safetensors` または `moss_image_sft_bf16.safetensors` を選びます。このキットの従来のBF16設定で試す場合は、KSamplerも **25 steps・CFG 2.5** に変更してください。CottonMossに戻すときは **12 steps・CFG 3** です。

## 仕上げと保存

**Runを1回**押すと、生成直後のPNGと、細かな粒を抑えて2倍に拡大したPNGの両方が保存されます。再拡散は行わず、元画像と拡大結果を混ぜて線の強さを調整します。全体に同じ処理を適用します。[2倍モデルと作例（Philip Hofmann）](https://huggingface.co/Phips/2xNomosUni_compact_otf_medium)

- 顔にざらつきが残る場合は「元画像を混ぜる割合」を初期値 **0.25** から **0.1** に下げます。肌が平らになりすぎたり、まつ毛が細くなったりしたら **0.5** に上げてください。拡大前の平滑化は「拡大前の粒状感を抑える」の半径を **0** にするとオフになります。
- 候補を続けて作るときは「仕上げ版を保存」をミュートしてRunすると、元画像だけを保存します。同じキュー内の再実行で構図を固定したいときはKSamplerのseedを固定してください。
- すでに保存した1枚を仕上げる場合は、このグラフに **Load Image** を追加してPNGを選びます。そのIMAGE出力を「拡大前の粒状感を抑える」の `image` と「元画像を混ぜる割合」の `image2` へつなぎ、「元画像を保存」をミュートしてRunします。これで生成・テキストエンコードの枝は実行対象から外れます。

PNGは `ComfyUI/output/MOSS/` 以下に保存されます。マリアンは `Marian/LastAffection/`、元のマルチャーナは `Marciana/Original33/`、30枚版は `Marciana/` の下の `Fast/` または `Quality/` を開いてください。元画像には `base_`、仕上げ版には `final_` が付きます。
