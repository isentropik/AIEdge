# Main-model training method

The bundled main float model uses the existing shared 8241-parameter polar Conv1D architecture. It is a single final-epoch development candidate, not a claim of independently established physical accuracy. Its SHA-256 is `723c5680bbae4f19e3eaee343a008cbca823e95a5da55d274f2afee33d0da9ca`. The secondary int8 model is unchanged.

`foreground_generator.py` contains the array-only synthetic method; `features_and_batch.py` contains the exact feature, target, architecture and batch methods. These modules never read photographs, train at import, download data or change production. The container does not include or execute this training directory. No data-loading or evaluation driver is provided here.

The source dataset and its per-image labels, source geometry and masks are private and are not distributed. Exact end-to-end reproduction needs those original inputs and their exclusion/provenance records; these methods alone do not imply public availability or bit-identical reproducibility. Before any training, reject excluded capture families and all descendants, verify every file hash and original label, and keep annotation uncertainty and the original records. Do not use diagnostic or protected evaluation images as training inputs.

## Fixed method

- Preserve the eight original training rows and existing linked-target policy. No new human labels are inferred from synthetic samples.
- Cross100 predeclared printed positions with three target-independent nuisance seeds to obtain300 main training-only renders. Core-color sampling uses the exact integer-pixel union of foreground cores minus uncertain-contact exclusions. No RGB crop, digit or printed background rotates with the procedural silhouette.
- Construct each imputed background once and reuse its exact bytes at every target for that seed. Hidden background is unknown; erasure/fill and geometry are explicitly uncertain development assumptions. A fixed residual body/shadow and synthetic style cues may remain.
- The copied `source_retained_outside_fixed_mask: true` field is retained as historical recipe metadata, not a literal hard-mask preservation guarantee. The Gaussian fill transition extends beyond the hard removal mask. Original pixels remain exact only outside the full nonzero fill-weight support; use the actual output bytes/hashes and effective fill support, not that legacy field, to assess pixel preservation.
- Synthetic foregrounds aim through the inherited pivot toward the declared printed rim coordinate. This convention applies only to synthetic construction; production model-output decoding is unchanged.
- Use12 original real +10 existing secondary synthetic +10 new main synthetic examples per32-example batch. Retain prior feature/target co-rotation for original real/secondary examples. New main examples already span targets and never co-rotate the background.
- Use seed921360,35epochs,20steps per epoch,Adam learning rate0.0005 and the final epoch only. Do not select checkpoints or adjust parameters using evaluation labels.
- Export one float32 model using a frozen concrete graph, with no quantization or optimization. Tensor contract remains `[1,384,40]` to `[1,360]`. Current preparation used TensorFlow2.16.1,Keras3.15.1,NumPy1.26.4 and Pillow12.3.0; this is not an assertion about older training runtime versions.

Run the data-free recipe tests with `python -m unittest discover -s aiedge_app/model_training -p test_recipe.py -v`. Existing runtime tensor/decoder/context-preservation tests remain required. A new model changes the pipeline identity and needs a separately reviewed stopped-service metadata rebind; the ordinary setup reference-inference path must not replay protected images. Independent real-image accuracy and deployment approval remain separate from method reproduction and synthetic parity.
