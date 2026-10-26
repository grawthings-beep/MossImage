# MOSS LoRA: PCから送信 → RunPodで自動学習

画像と同名の `.txt` キャプションが入った `train` フォルダを、設定と一緒に送ります。Podでは返された1行を貼ると、受信・検証・展開・環境準備・Pre-Cache・学習・LoRA保存が順番に動きます。AcademiaSDの画面で設定を入力する必要はありません。

## RunPodの準備

- 生成用と同じ、CUDA版PyTorch 2.9以上・Python 3.12以上のGPU Podを使用します。
- `/workspace` は100GB、RAMは64GBを目安にします。モデルのダウンロード前に空き容量を確認します。
- 学習はMOSS-Image BaseのNF4、テキストエンコーダーはBF16＋CPUオフロードです。GPUごとの速度・最大解像度は未計測です。
- 学習にWebポートは不要です。iPhoneから操作する場合はJupyterLabの8888を使えます。
- 生成サーバーが起動している場合は、生成が終わってから停止してください。ブラウザの画面を閉じるだけではサーバーは停止しません。既存のGPU処理があれば学習は `WAITING` になります。
- `HF_TOKEN` はPodの既存の環境変数を使用します。転送ファイルには含めません。

このrepoをまだ取得していなければ:

```bash
cd /workspace && git clone https://github.com/grawthings-beep/MossImage.git
```

取得済みなら、ジョブが動いていないときに更新します:

```bash
cd /workspace/MossImage && git pull --ff-only
```

同じPodを生成から学習へ切り替える場合、生成が完了してから次を実行します。この保存先を使う生成サーバーだけを停止します。

```bash
bash /workspace/MossImage/background.sh --stop
```

学習が終わったら `bash /workspace/MossImage/background.sh` で生成を再開できます。

`start.sh` は画像生成用です。学習だけの場合、起動する必要はありません。学習用環境は最初のジョブで自動準備します。`runpodctl receive` がなければ、x86_64のPodでは固定版2.14.0をSHA256検証付きで取得します。

## PC側: データセットをまとめて送る

PCにPython 3.12以上と `runpodctl.exe` が必要です。既存のAnima用 `runpodctl.exe` を使えます。送信前にPodで上のrepo準備を済ませてください。

repo内のPowerShellで、データセットの場所・ジョブ名・トリガーを指定します。この例のパスは手元のフォルダに置き換えてください。

```powershell
.\training\Send-Dataset.ps1 -Dataset 'C:\datasets\my_character\train' -Name my_character -Trigger mych4r
```

送信準備だけなら末尾に `-PrepareOnly`。Pythonの場所を指定する場合は `-Python 'C:\path\to\python.exe'`、runpodctlの場所は `-Runpodctl 'C:\path\to\runpodctl.exe'`。学習設定を変える場合は、`training/recipe.json` をコピーして編集し、`-Recipe 'C:\path\to\recipe.json'` を指定します。

通常実行すると送信プロセスが裏で待機し、結果の **`command` に実際の受信コードとSHA256を含む1行**が出ます。その行をRunPodのターミナルに貼ります。受信が済むまで送信元PCを起動・接続したままにしてください。

**`WORKER_PID=...` が表示されたら、受信から先はバックグラウンド処理です。Safariを離れたり、ターミナルを閉じても続きます。PodのStop/Terminateでは止まります。**

コードは使い切りです。送信済みのコードを再利用しません。送信に失敗した場合は送信ログを確認し、新たに送るときだけ `-NewTransfer` を指定します。同じ送信プロセスがまだ生きていれば、そのコードを再利用します。

## 途中経過・再開

以下の `my_character` は送ったジョブ名です。

```bash
bash /workspace/MossImage/train.sh logs my_character
```

ログ表示中のCtrl+Cは表示だけを止めます。状態だけを見る場合:

```bash
bash /workspace/MossImage/train.sh status my_character
```

失敗・Pod再起動後に再開する場合:

```bash
bash /workspace/MossImage/train.sh resume my_character
```

受信済みなら再送不要です。検証済みキャッシュと保存済み学習状態を使います。再開は最後に保存されたstepからで、中断時点と完全に同一の乱数状態を再現するものではありません。完成済みなら再学習・上書きしません。

状態は `RECEIVING → QUEUED/WAITING → SETTING_UP → PRECACHE → TRAINING → COMPLETE`。失敗時は `FAILED` に理由を記録して止まり、自動で繰り返しません。

## 保存先

| 内容 | 場所 |
|---|---|
| 完成LoRA | `/workspace/moss-training/outputs/mossimage_lora_my_character.safetensors` |
| ログ・状態 | `/workspace/moss-training/jobs/my_character/train.log` / `status.json` |
| 受信した画像とキャプション | `/workspace/moss-training/jobs/my_character/train/` |
| 学習設定 | `/workspace/moss-training/jobs/my_character/settings/` |
| 途中LoRA・再開用状態 | `/workspace/moss-training/jobs/my_character/Outputs/mossimage_lora_output_my_character/` |
| 共有モデルとvenv | `/workspace/moss-training/Models/` / `venvs/` |

完成LoRAはComfyUIの `models/loras/` に置いて使用できます。自動でHugging Faceへアップロードしたり、生成用LoRAを置き換えたり、Podを停止したりはしません。

## 既定の学習設定

前回のマリアン：クイーンの保存済み学習メタデータに合わせた出発点です。別キャラの品質を保証する設定ではありません。

| 設定 | 値 |
|---|---|
| Base | MOSS-Image Base / NF4 |
| Text Encoder | BF16 CPU offload |
| 解像度 | 面積1024×1024、縦横比bucket、最大辺1536、16px単位 |
| Steps / 保存間隔 | 2000 / 250 |
| Rank / Alpha | 16 / 16 |
| LR / Scheduler | 0.0001 / constant |
| Batch / Grad accumulation | 1 / 1 |
| Optimizer / timestep sampling | AdamW / MOSS方式 |
| Seed | 42 |

`constant` では上流実装上warmupが無効です。設定ファイルの100は前回の保存値を残しています。Animaのrank32/alpha1/repeat/epoch設定は流用していません。

入力は通常のキャラクターLoRA用です。PNG/JPG/JPEG/WebPと対応するUTF-8の `.txt` を同じ階層に置き、各captionにトリガーを含めます。既存の画像やcaptionは改変しません。編集LoRA用before/afterペアや動画は対象外です。

## 実装と検証範囲

- [AcademiaSD LoRAlab](https://github.com/AcademiaSD/AcademiaSD_LoRAlab-TrainerStudio)の固定コミットのスクリプトを取得。各ソースのSHA256を検証し、キャラごとに独立したフォルダで実行します。
- モデルも固定リビジョンで取得。生成用のComfyUI環境と別venvを使い、PodのCUDA PyTorch系パッケージは制約で保護します。
- 学習前にCUDA BF16演算、bitsandbytesのNF4 forward/backward、画像デコード、キャッシュ形状を実際に検査します。
- 送受信時のチェックサム・画像caption対応・トリガー確認、展開先の逸脱防止、二重起動防止、完成ファイルのstep/キャラ/形式検証を行います。
- ローカル検証とGPUでの実学習の確認は分けて記録しています。詳細は [VALIDATION.md](VALIDATION.md)。
