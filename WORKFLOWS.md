# ComfyUIのワークフローで生成・参照・編集

7860のURLを開くと通常のComfyUIが表示されます。**Workflows** から次のJSONを開き、プロンプト・画像を指定して **Run / Queue** を押します。ファイルをPCに保存してComfyUIへドラッグしても読み込めます。カスタムノードは不要です。

| ファイル | 用途 | 初期設定 |
|---|---|---|
| [MOSS_05 CottonMoss](workflows/MOSS_05_CottonMoss_1152x1536_12.json) | 選択中のCottonMoss Turbo INT8で通常生成（キャラLoRAなし） | 1152×1536・12 steps |
| [MOSS_06 CottonMoss＋マリアン](workflows/MOSS_06_CottonMoss_marian_queen2_1152x1536_12.json) | CottonMoss＋マリアンLoRA | 1152×1536・12 steps |
| [MOSS_07 CottonMoss＋紅蓮](workflows/MOSS_07_CottonMoss_scarlet_goddeath_1152x1536_12.json) | CottonMoss＋紅蓮LoRA | 1152×1536・12 steps |
| [MOSS_01 紅蓮](workflows/MOSS_01_scarlet_goddeath_1152x1536_25.json) | 紅蓮LoRAで通常生成 | 1152×1536・25 steps |
| [MOSS_02 マリアン](workflows/MOSS_02_marian_queen2_1152x1536_25.json) | マリアンLoRAで通常生成 | 1152×1536・25 steps |
| [MOSS_03 CharRef](workflows/MOSS_03_CharRef_1152x1536_25.json) | 画像のキャラを別衣装・ポーズ・場面で生成 | 1152×1536・25 steps |
| [MOSS_04 Edit HQ v5](workflows/MOSS_04_EditHQ_v5_25.json) | 元画像の指定箇所・内容を文章で変更 | 元画像の比率で約1MP・25 steps |

## 通常生成

**CottonMossを使う場合は05〜07を開きます。** モデルは [CottonMoss base_turbo_test_int8](https://civitai.red/models/3026318/cottonmoss?modelVersionId=3437076)、指定ファイルID 3334385です。作者推奨の12 steps・CFG 3・er_sdeと、作例のsimple・SLG 22（前半50%）を採用。高速化アダプターはマージ済みなので追加しません。作例のカスタムキャッシュノードは使用せず、標準ノードで構成します。作者も試作段階・キャラ再現の難しさを明記しており、品質と速度は実GPUで未評価です。

品質タグ `masterpiece, best quality, highres, absurdres` を正条件の先頭に置き、作者のnegative promptを設定済みです。Qwen BF16とsmall VAEを継続使用します。01〜04は元の構成を保持しており、CottonMossへ自動置換しません。

緑の正条件テキストノードでプロンプトを変更します。紅蓮の `sc4rl3tg0d`、マリアンの `m4r14nqu33n2` は残します。着せ替える場合は元衣装の説明を新しい服に書き換えます。JSONプロンプトも同じ欄へ入力できます。

サイズは **Empty Flux2 Latent Image**、ステップ・seedは **KSampler**、キャラLoRAの強度は **Load LoRA Model Only** で変更します。独自画面によるプロンプトの自動追加はありません。

## 画像からキャラを参照

1. **① 元画像をアップロード / Load Image** でキャラ画像を選びます。
2. **② 新しい衣装・ポーズ・場面** に描きたい内容を書きます。先頭の `Same character and art style as Picture 1.` は残します。
3. Run。元画像のキャラと画風を参考に、新しい1枚を生成します。

キャラLoRAは重ねません。画像中の元衣装を変更したければ新しい服を明記します。顔・髪・目の特徴を少し添えると識別を補助できます。1人のキャラが見やすい参照画像を使用してください。顔・髪の細部が完全固定される機能ではありません。[CharRef作者の説明](https://huggingface.co/7err4/MOSS-Image-CharRef)。

## 元画像を編集

**MOSS_04**で元画像をアップロードし、正条件に変更内容と維持する要素を記入します。例：

```text
Change her outfit to a black evening dress. Keep her face, hair, pose, background and composition unchanged.
```

SFT＋Edit HQ v5を使用します。v5は作者が推奨する版で、v6の色かぶり等の問題を避ける判断です。[作者の比較・説明](https://huggingface.co/akhaliq/MOSS-Image-Edit-HQ)。元画像を約1MP・16px単位に調整し、その縦横比で出力します。縦横サイズは **Get Image Size** から自動接続しているため、固定サイズへの引き伸ばしは行いません。既存の旧画面の矩形切り抜き・貼り戻しUIはありません。このワークフローは画像全体を編集します。

参照と編集は正負両方のエンコーダーに同じ画像・VAEを接続し、`edit_format=ai-toolkit`、負条件は空欄にしています。この接続は維持してください。

## ステップと進捗

CottonMossの05〜07は12 steps、CFG 3。従来の01〜04は25 steps、CFG 2.5。どちらもer_sde / simple、SLG layer 22・前半50%です。CharRef/Edit HQ作者の評価設定と比べたい場合は50 steps、CFG 3、euler / sgm_uniform、SLG end_percent 1.0に変更できます。各設定の実GPU画質比較はこのキットでは未実施です。

進捗はComfyUI標準のノード表示とキューを使用します。起動時に `latent2rgb` の途中プレビューを有効にします。完成画像は **Save Image** に表示され、`ComfyUI/output/MOSS/` にPNGで保存されます。

## 自動準備と以前の保存物

起動時にCottonMoss（約5.4GB、指定の`uwgm/Moss`からHF_TOKENで取得）、参照用CharRef・編集用SFTとv5アダプター（約10.8GB）もダウンロード・検証します。CIVITAI_TOKENは不要です。ブラウザー側でモデル導入コマンドは不要です。CottonMossを手動配置する場合は `ComfyUI/models/diffusion_models/cottonmoss_baseTurboTestInt8.safetensors` に置くと、同じサイズ・SHA256なら再取得しません。

利用者が編集したワークフローは上書きしません。同名のJSONを更新したい場合は、GitHubから新しいJSONを開いて別名で保存してください。旧画面の画像とデータは `moss-image-runtime/studio/`、元の生成PNGは `ComfyUI/output/MOSS/Studio/` に残ります。
