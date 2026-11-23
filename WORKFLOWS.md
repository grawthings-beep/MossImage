# マリアンとマルチャーナをComfyUIで生成する

RunPodの **Connect → 7860 → Workflows** でキャラとLoRAの版を選びます。どのワークフローにも対応するLoRAとトリガーが設定されています。緑の欄で衣装・ポーズ・背景を書いて **Run** を押してください。

| キャラLoRA | トリガー | 速く試す（864×1152 → 1296×1728） | 細部を優先（1152×1536 → 1728×2304） |
|---|---|---|---|
| マリアン：ラストアフェクション・3000ステップ版 | `m4r14nl4st2` | [Fast Hires](workflows/MOSS_10_Fast_Hires_marian_last_affection2_3k.json) | [Quality Hires](workflows/MOSS_08_Quality_Hires_marian_last_affection2_3k.json) |
| マルチャーナ：マリンスタディ・元の33枚版 | `m4rc14n4m4r1ne` | [Fast Hires](workflows/MOSS_10_Fast_Hires_marciana_marine_study_original_33.json) | [Quality Hires](workflows/MOSS_08_Quality_Hires_marciana_marine_study_original_33.json) |
| マルチャーナ：マリンスタディ・30枚版 v1 | `m4rc14n4m4r1ne` | [Fast Hires](workflows/MOSS_10_Fast_Hires_marciana_marine_study_30_v1.json) | [Quality Hires](workflows/MOSS_08_Quality_Hires_marciana_marine_study_30_v1.json) |

1段目の初期値はCottonMoss Turbo INT8、キャラLoRA強度1.0、12 steps、CFG 3、er_sde / simple、SLG layer 22（前半50%）です。Fast版は、拡散で処理する画素数がQuality版より約44%少なくなります。[CottonMoss作者の設定](https://civitai.red/models/3026318/cottonmoss?modelVersionId=3437076)

**生成モデルを切り替える**には、左端の「CottonMoss Turbo INT8」ノードで `moss_image_base_bf16.safetensors` または `moss_image_sft_bf16.safetensors` を選びます。このキットの従来のBF16設定で試す場合は、1段目のKSamplerも **25 steps・CFG 2.5** に変更してください。CottonMossに戻すときは **12 steps・CFG 3** です。

## 仕上げと保存

**Runを1回**押すと、1段目の画像と、拡大後に描き込んだ画像を両方保存します。1段目のKSamplerが出したlatentを `LatentUpscaleBy` で1.5倍に拡大し、同じMOSSモデル・キャラLoRA・プロンプトで2段目のKSamplerを実行します。参照したAnimaの配布ワークフローと同じ **bislerp・8 steps・CFG 1・er_sde / simple・denoise 0.55** です。[Animaの2段階ノード](https://github.com/grawthings-beep/anima-image-runpod/blob/2ecfe65542755a0ed008560021a43977ceade324/workflows/graphs/anima_negpip_latent_2pass.json)

- **描き込みの強さ**は2段目の `denoise` で調整します。顔つきや衣装が変わりすぎる場合は0.40を目安に下げてください。同じ構図で比較するときは両方のseedを固定します。
- **仕上げの大きさ**は「2段目：latent拡大」の `scale_by` で変更できます。Quality版で従来の出力サイズ（2304×3072）が必要なら `2.0` にしてください。初期値の `1.5` より仕上げに時間とVRAMを使います。
- **構図だけを試すとき**は「仕上げ版を保存」をミュートしてRunします。構図を決めたらミュートを解除してください。同じセッションで1段目の結果がキャッシュされていれば、そこから仕上げに進みます。
- **保存済みのPNGから仕上げるとき**は `Load Image → VAE Encode` を追加し、既存のVAEをつなぎます。そのLATENT出力を「2段目：latent拡大」の入力へつなぎ、「元画像を保存」をミュートしてRunします。PNGからの再エンコードでは、最初の生成で使ったlatentとわずかに異なる場合があります。

PNGは `ComfyUI/output/MOSS/` 以下に保存されます。マリアンは `Marian/LastAffection/`、元のマルチャーナは `Marciana/Original33/`、30枚版は `Marciana/` の下の `Fast/` または `Quality/` を開いてください。元画像には `base_`、仕上げ版には `final_` が付きます。
