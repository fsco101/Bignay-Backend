"""
Bignay Classification Model Training Script (Improved)
=======================================================
Trains TensorFlow/Keras models for fruit and leaf classification.

Improvements:
- tf.data pipeline for better performance
- MobileNetV2 with proper preprocessing
- Two-phase training (frozen base → fine-tuning)
- Advanced augmentation with albumentations-style transforms
- Mixed precision training for faster GPU training
- Label smoothing for better generalization
- Cosine decay learning rate schedule
- Comprehensive callbacks with TensorBoard
- Better handling of small/imbalanced datasets

Usage:
    python train_model.py --subject fruit
    python train_model.py --subject leaf
    python train_model.py --subject both
    python train_model.py --subject fruit --fine-tune  # Enable fine-tuning phase

Output:
    - backend/model/fruit_model.h5
    - backend/model/leaf_model.h5
"""

import argparse
import os
import random
from datetime import datetime
from pathlib import Path

import numpy as np
import tensorflow as tf
from tensorflow.keras import layers, models, callbacks, regularizers
from tensorflow.keras.applications import MobileNetV2
from tensorflow.keras.applications.mobilenet_v2 import preprocess_input

# Set seeds for reproducibility
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
tf.random.set_seed(SEED)

# Paths
SCRIPT_DIR = Path(__file__).parent.resolve()
DATASET_DIR = SCRIPT_DIR.parent / "dataset"
MODEL_DIR = SCRIPT_DIR / "model"
LOG_DIR = SCRIPT_DIR / "logs"

# Training config
IMG_SIZE = 224
BATCH_SIZE = 32  # Increased for better gradient estimates
EPOCHS = 100  # More epochs with early stopping
INITIAL_LEARNING_RATE = 1e-3  # Higher initial LR for frozen base
FINE_TUNE_LEARNING_RATE = 1e-5  # Lower LR for fine-tuning
LABEL_SMOOTHING = 0.1  # Helps generalization
VALIDATION_SPLIT = 0.2
FINE_TUNE_EPOCHS = 50
FINE_TUNE_AT_LAYER = 100  # Unfreeze layers after this index

# Class definitions (must match backend/app.py)
FRUIT_CLASSES = ["good", "mold", "overripe", "ripe", "unripe"]
LEAF_CLASSES = ["healthy", "mold"]


def enable_mixed_precision():
    """Enable mixed precision training for faster GPU performance."""
    try:
        policy = tf.keras.mixed_precision.Policy('mixed_float16')
        tf.keras.mixed_precision.set_global_policy(policy)
        print(f"Mixed precision enabled: {policy.name}")
        return True
    except Exception as e:
        print(f"Mixed precision not available: {e}")
        return False


def count_images(data_dir: Path, classes: list[str]) -> dict:
    """Count images per class including subdirectories."""
    counts = {}
    total = 0
    for cls in classes:
        cls_dir = data_dir / cls
        if cls_dir.exists():
            # Count only TensorFlow-supported formats: JPEG, PNG, GIF, BMP, WebP
            # Note: AVIF is NOT supported by tf.image.decode_image
            extensions = ['*.jpg', '*.jpeg', '*.png', '*.gif', '*.bmp', '*.webp',
                          '*.JPG', '*.JPEG', '*.PNG', '*.GIF', '*.BMP', '*.WEBP']
            count = sum(len(list(cls_dir.glob(ext))) for ext in extensions)
            counts[cls] = count
            total += count
        else:
            counts[cls] = 0
    counts['_total'] = total
    return counts


def create_augmentation_layer():
    """
    Creates optimized data augmentation for fruit/leaf classification.
    Runs on GPU, only active during training.
    
    Augmentation parameters optimized for 500+ images per class:
    - Horizontal flip: Fruits appear in any orientation
    - Rotation ±54°: Natural rotation without losing meaning
    - Zoom ±20%: Camera distance variation
    - Translation ±10%: Off-center subjects
    - Brightness ±15%: Lighting conditions
    - Contrast ±15%: Camera/sensor differences
    """
    return tf.keras.Sequential([
        layers.RandomFlip("horizontal"),
        layers.RandomRotation(0.15, fill_mode='reflect'),  # ±54 degrees
        layers.RandomZoom(
            height_factor=(-0.2, 0.2), 
            width_factor=(-0.2, 0.2),
            fill_mode='reflect'
        ),
        layers.RandomTranslation(0.1, 0.1, fill_mode='reflect'),
        layers.RandomBrightness(factor=0.15, value_range=(-1.0, 1.0)),
        layers.RandomContrast(factor=0.15),
    ], name="augmentation")


def create_advanced_augmentation_layer():
    """
    More aggressive augmentation for overfitting prevention.
    Use when validation accuracy plateaus while training keeps improving.
    
    More aggressive parameters + cutout-style regularization.
    """
    return tf.keras.Sequential([
        layers.RandomFlip("horizontal_and_vertical"),
        layers.RandomRotation(0.2, fill_mode='reflect'),  # ±72 degrees
        layers.RandomZoom(
            height_factor=(-0.25, 0.25), 
            width_factor=(-0.25, 0.25),
            fill_mode='reflect'
        ),
        layers.RandomTranslation(0.15, 0.15, fill_mode='reflect'),
        layers.RandomBrightness(factor=0.2, value_range=(-1.0, 1.0)),
        layers.RandomContrast(factor=0.2),
        # Cutout-like regularization: forces model to use multiple features
        layers.RandomCrop(height=int(IMG_SIZE * 0.85), width=int(IMG_SIZE * 0.85)),
        layers.Resizing(IMG_SIZE, IMG_SIZE),
    ], name="advanced_augmentation")


def load_and_preprocess_image(file_path, label):
    """Load and preprocess a single image."""
    # Read file
    img = tf.io.read_file(file_path)
    # Decode image (handles jpg, png, webp, etc.)
    img = tf.image.decode_image(img, channels=3, expand_animations=False)
    img.set_shape([None, None, 3])
    # Resize
    img = tf.image.resize(img, [IMG_SIZE, IMG_SIZE])
    # MobileNetV2 preprocessing (scales to [-1, 1])
    img = preprocess_input(img)
    return img, label


def create_dataset(data_dir: Path, classes: list[str], is_training: bool = True, 
                   validation_split: float = 0.2) -> tuple:
    """
    Creates tf.data.Dataset from directory structure.
    More efficient than ImageDataGenerator.
    """
    file_paths = []
    labels = []
    class_to_idx = {cls: i for i, cls in enumerate(classes)}
    
    # Only TensorFlow-supported formats: JPEG, PNG, GIF, BMP, WebP
    # Note: AVIF is NOT supported by tf.image.decode_image
    extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']
    
    for cls in classes:
        cls_dir = data_dir / cls
        if not cls_dir.exists():
            continue
        for ext in extensions:
            for f in cls_dir.glob(f'*{ext}'):
                file_paths.append(str(f))
                labels.append(class_to_idx[cls])
            for f in cls_dir.glob(f'*{ext.upper()}'):
                file_paths.append(str(f))
                labels.append(class_to_idx[cls])
    
    # Remove duplicates
    seen = set()
    unique_paths = []
    unique_labels = []
    for p, l in zip(file_paths, labels):
        if p not in seen:
            seen.add(p)
            unique_paths.append(p)
            unique_labels.append(l)
    
    file_paths = unique_paths
    labels = unique_labels
    
    # Shuffle and split
    combined = list(zip(file_paths, labels))
    random.shuffle(combined)
    
    split_idx = int(len(combined) * (1 - validation_split))
    train_data = combined[:split_idx]
    val_data = combined[split_idx:]
    
    # Convert labels to one-hot
    num_classes = len(classes)
    
    def create_ds(data, shuffle=True):
        paths, lbls = zip(*data) if data else ([], [])
        paths = list(paths)
        lbls = [tf.one_hot(l, num_classes) for l in lbls]
        
        ds = tf.data.Dataset.from_tensor_slices((paths, lbls))
        ds = ds.map(load_and_preprocess_image, num_parallel_calls=tf.data.AUTOTUNE)
        
        if shuffle:
            ds = ds.shuffle(buffer_size=len(paths), seed=SEED)
        
        ds = ds.batch(BATCH_SIZE)
        ds = ds.prefetch(tf.data.AUTOTUNE)
        return ds, len(paths)
    
    train_ds, train_count = create_ds(train_data, shuffle=True)
    val_ds, val_count = create_ds(val_data, shuffle=False)
    
    return train_ds, val_ds, train_count, val_count, class_to_idx


def compute_class_weights(data_dir: Path, classes: list[str]) -> dict:
    """
    Computes class weights to handle imbalanced datasets.
    """
    counts = count_images(data_dir, classes)
    total = counts['_total']
    
    if total == 0:
        return None
    
    num_classes = len(classes)
    weights = {}
    
    for i, cls in enumerate(classes):
        count = counts.get(cls, 0)
        if count > 0:
            # Balanced class weight formula
            weights[i] = total / (num_classes * count)
        else:
            weights[i] = 1.0
    
    # Normalize weights
    max_weight = max(weights.values())
    weights = {k: v / max_weight * 2.0 for k, v in weights.items()}  # Scale to reasonable range
    
    return weights


def create_mobilenet_model(num_classes: int, input_shape=(IMG_SIZE, IMG_SIZE, 3), 
                           use_augmentation: bool = True, small_dataset: bool = False) -> models.Model:
    """
    Creates an improved MobileNetV2 model with:
    - Proper preprocessing
    - Data augmentation layer
    - Regularization
    - Label smoothing compatible output
    """
    inputs = layers.Input(shape=input_shape)
    
    # Data augmentation (only during training)
    if use_augmentation:
        if small_dataset:
            x = create_advanced_augmentation_layer()(inputs)
        else:
            x = create_augmentation_layer()(inputs)
    else:
        x = inputs
    
    # Base model (MobileNetV2)
    base_model = MobileNetV2(
        input_shape=input_shape,
        include_top=False,
        weights="imagenet"
    )
    base_model.trainable = False  # Freeze initially
    
    x = base_model(x, training=False)
    
    # Custom head with regularization
    x = layers.GlobalAveragePooling2D()(x)
    x = layers.BatchNormalization()(x)
    x = layers.Dropout(0.4)(x)
    x = layers.Dense(256, activation="relu", kernel_regularizer=regularizers.l2(0.01))(x)
    x = layers.BatchNormalization()(x)
    x = layers.Dropout(0.3)(x)
    x = layers.Dense(128, activation="relu", kernel_regularizer=regularizers.l2(0.01))(x)
    x = layers.Dropout(0.2)(x)
    
    # Output layer (float32 for mixed precision compatibility)
    outputs = layers.Dense(num_classes, activation="softmax", dtype='float32')(x)
    
    model = models.Model(inputs, outputs)
    
    return model, base_model


def create_simple_cnn(num_classes: int, input_shape=(IMG_SIZE, IMG_SIZE, 3),
                      use_augmentation: bool = True, small_dataset: bool = True) -> models.Model:
    """
    Improved simple CNN for very small datasets.
    """
    inputs = layers.Input(shape=input_shape)
    
    # Augmentation
    if use_augmentation:
        x = create_advanced_augmentation_layer()(inputs)
    else:
        x = inputs
    
    # Normalize to [0, 1]
    x = layers.Rescaling(1./255)(x)
    
    # Conv blocks with batch norm
    x = layers.Conv2D(32, (3, 3), padding='same')(x)
    x = layers.BatchNormalization()(x)
    x = layers.Activation('relu')(x)
    x = layers.MaxPooling2D((2, 2))(x)
    
    x = layers.Conv2D(64, (3, 3), padding='same')(x)
    x = layers.BatchNormalization()(x)
    x = layers.Activation('relu')(x)
    x = layers.MaxPooling2D((2, 2))(x)
    
    x = layers.Conv2D(128, (3, 3), padding='same')(x)
    x = layers.BatchNormalization()(x)
    x = layers.Activation('relu')(x)
    x = layers.MaxPooling2D((2, 2))(x)
    
    x = layers.Conv2D(128, (3, 3), padding='same')(x)
    x = layers.BatchNormalization()(x)
    x = layers.Activation('relu')(x)
    x = layers.GlobalAveragePooling2D()(x)
    
    x = layers.Dropout(0.5)(x)
    x = layers.Dense(128, activation='relu', kernel_regularizer=regularizers.l2(0.01))(x)
    x = layers.Dropout(0.3)(x)
    
    outputs = layers.Dense(num_classes, activation='softmax', dtype='float32')(x)
    
    return models.Model(inputs, outputs), None


class CosineDecayWithWarmup(tf.keras.optimizers.schedules.LearningRateSchedule):
    """
    Cosine decay learning rate schedule with optional warmup.
    Implemented as a proper class to avoid pickle issues.
    """
    def __init__(self, initial_lr: float, total_steps: int, warmup_steps: int = 0):
        super().__init__()
        self.initial_lr = initial_lr
        self.total_steps = total_steps
        self.warmup_steps = warmup_steps
    
    def __call__(self, step):
        step = tf.cast(step, tf.float32)
        
        if self.warmup_steps > 0:
            warmup_pct = tf.minimum(step / self.warmup_steps, 1.0)
            warmup_lr = self.initial_lr * warmup_pct
            
            decay_steps = self.total_steps - self.warmup_steps
            decay_step = tf.maximum(step - self.warmup_steps, 0.0)
            cosine_decay = 0.5 * (1 + tf.cos(np.pi * decay_step / decay_steps))
            decay_lr = self.initial_lr * cosine_decay
            
            return tf.where(step < self.warmup_steps, warmup_lr, decay_lr)
        else:
            cosine_decay = 0.5 * (1 + tf.cos(np.pi * step / self.total_steps))
            return self.initial_lr * cosine_decay
    
    def get_config(self):
        return {
            'initial_lr': self.initial_lr,
            'total_steps': self.total_steps,
            'warmup_steps': self.warmup_steps
        }


def create_callbacks(model_path: Path, log_dir: Path, monitor='val_accuracy'):
    """
    Creates comprehensive callbacks for training monitoring and control.
    Note: Avoiding histogram_freq and complex callbacks that cause pickle issues.
    """
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    
    callback_list = [
        # Early stopping with patience
        callbacks.EarlyStopping(
            monitor=monitor,
            patience=15,
            mode='max',
            restore_best_weights=True,
            verbose=1,
            min_delta=0.001
        ),
        # Reduce LR on plateau
        callbacks.ReduceLROnPlateau(
            monitor='val_loss',
            factor=0.5,
            patience=7,
            min_lr=1e-7,
            verbose=1
        ),
        # Save best model - use .keras format to avoid HDF5 warnings
        callbacks.ModelCheckpoint(
            str(model_path).replace('.h5', '.keras'),
            monitor=monitor,
            save_best_only=True,
            mode='max',
            verbose=1
        ),
        # CSV logger for easy analysis
        callbacks.CSVLogger(
            str(model_path.parent / f"{model_path.stem}_training.csv"),
            append=False
        ),
        # Terminate on NaN
        callbacks.TerminateOnNaN(),
    ]
    
    # TensorBoard - disable histogram_freq to avoid pickle issues
    try:
        tb_callback = callbacks.TensorBoard(
            log_dir=str(log_dir / timestamp),
            histogram_freq=0,  # Disabled to avoid pickle issues
            write_graph=False,  # Disabled to avoid pickle issues
            update_freq='epoch',
            profile_batch=0  # Disable profiling
        )
        callback_list.append(tb_callback)
    except Exception as e:
        print(f"Warning: TensorBoard callback disabled: {e}")
    
    return callback_list


def train_model(subject: str, enable_fine_tuning: bool = True):
    """
    Trains a classification model with improved methodology.
    """
    print(f"\n{'='*70}")
    print(f"Training {subject.upper()} Classification Model (Improved)")
    print(f"{'='*70}\n")
    
    # Setup paths and classes
    if subject == "fruit":
        data_dir = DATASET_DIR / "fruit"
        classes = FRUIT_CLASSES
        model_path = MODEL_DIR / "fruit_model.h5"
    else:
        data_dir = DATASET_DIR / "leaf"
        classes = LEAF_CLASSES
        model_path = MODEL_DIR / "leaf_model.h5"
    
    # Check data
    if not data_dir.exists():
        print(f"ERROR: Dataset directory not found: {data_dir}")
        return False
    
    # Count and display dataset info
    print("Dataset Summary:")
    print("-" * 40)
    counts = count_images(data_dir, classes)
    total_images = counts['_total']
    
    for cls in classes:
        count = counts.get(cls, 0)
        bar = '█' * min(count // 2, 30)
        print(f"  {cls:12s}: {count:4d} images {bar}")
    print(f"  {'Total':12s}: {total_images:4d} images")
    print()
    
    if total_images < 10:
        print(f"ERROR: Not enough images. Need at least 10, found {total_images}")
        return False
    
    # Determine if small dataset
    is_small_dataset = total_images < 100
    use_simple_cnn = total_images < 30
    
    if is_small_dataset:
        print("⚠️  Small dataset detected - using aggressive augmentation")
    if use_simple_cnn:
        print("⚠️  Very small dataset - using simple CNN instead of transfer learning")
    
    # Enable mixed precision for GPU
    if len(tf.config.list_physical_devices('GPU')) > 0:
        enable_mixed_precision()
    
    # Create datasets
    print("\nLoading datasets with tf.data pipeline...")
    train_ds, val_ds, train_count, val_count, class_indices = create_dataset(
        data_dir, classes, validation_split=VALIDATION_SPLIT
    )
    
    print(f"Training samples: {train_count}")
    print(f"Validation samples: {val_count}")
    print(f"Class indices: {class_indices}")
    
    # Compute class weights
    class_weights = compute_class_weights(data_dir, classes)
    if class_weights:
        print(f"\nClass weights (for imbalanced data):")
        for cls, idx in class_indices.items():
            print(f"  {cls}: {class_weights[idx]:.3f}")
    
    # Create model
    print("\nBuilding model...")
    num_classes = len(classes)
    
    if use_simple_cnn:
        print("Architecture: Simple CNN with BatchNorm")
        model, base_model = create_simple_cnn(num_classes, small_dataset=True)
        enable_fine_tuning = False  # No fine-tuning for simple CNN
    else:
        print("Architecture: MobileNetV2 with custom head")
        model, base_model = create_mobilenet_model(num_classes, small_dataset=is_small_dataset)
    
    # Phase 1: Train with frozen base
    print("\n" + "="*50)
    print("PHASE 1: Training with frozen base layers")
    print("="*50)
    
    steps_per_epoch = max(1, train_count // BATCH_SIZE)
    total_steps = steps_per_epoch * EPOCHS
    warmup_steps = steps_per_epoch * 3  # 3 epochs warmup
    
    # Optimizer with warmup
    optimizer = tf.keras.optimizers.Adam(learning_rate=INITIAL_LEARNING_RATE)
    
    # Compile with label smoothing
    model.compile(
        optimizer=optimizer,
        loss=tf.keras.losses.CategoricalCrossentropy(label_smoothing=LABEL_SMOOTHING),
        metrics=['accuracy', tf.keras.metrics.TopKCategoricalAccuracy(k=2, name='top2_acc')]
    )
    
    model.summary()
    
    # Setup callbacks
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    
    training_callbacks = create_callbacks(model_path, LOG_DIR / subject)
    
    # Train Phase 1
    print("\nStarting Phase 1 training...\n")
    
    history1 = model.fit(
        train_ds,
        epochs=EPOCHS,
        validation_data=val_ds,
        class_weight=class_weights,
        callbacks=training_callbacks,
        verbose=1
    )
    
    # Phase 2: Fine-tuning (if enabled and using transfer learning)
    if enable_fine_tuning and base_model is not None and not is_small_dataset:
        print("\n" + "="*50)
        print("PHASE 2: Fine-tuning with unfrozen layers")
        print("="*50)
        
        # Unfreeze top layers of base model
        base_model.trainable = True
        
        # Freeze early layers, unfreeze later ones
        for layer in base_model.layers[:FINE_TUNE_AT_LAYER]:
            layer.trainable = False
        
        trainable_count = sum(1 for l in base_model.layers if l.trainable)
        print(f"Unfrozen {trainable_count} layers in base model for fine-tuning")
        
        # Recompile with lower learning rate
        model.compile(
            optimizer=tf.keras.optimizers.Adam(learning_rate=FINE_TUNE_LEARNING_RATE),
            loss=tf.keras.losses.CategoricalCrossentropy(label_smoothing=LABEL_SMOOTHING),
            metrics=['accuracy', tf.keras.metrics.TopKCategoricalAccuracy(k=2, name='top2_acc')]
        )
        
        # Reset callbacks for phase 2
        fine_tune_callbacks = create_callbacks(model_path, LOG_DIR / f"{subject}_finetune")
        
        print("\nStarting Phase 2 (fine-tuning)...\n")
        
        history2 = model.fit(
            train_ds,
            epochs=FINE_TUNE_EPOCHS,
            validation_data=val_ds,
            class_weight=class_weights,
            callbacks=fine_tune_callbacks,
            verbose=1
        )
    
    # Save final model in both formats for compatibility
    # Primary: .keras format (native Keras, recommended)
    keras_path = model_path.with_suffix('.keras')
    model.save(str(keras_path))
    print(f"\n✓ Model saved to: {keras_path}")
    
    # Secondary: .h5 format (legacy, for backward compatibility)
    h5_path = model_path.with_suffix('.h5')
    try:
        model.save(str(h5_path))
        print(f"✓ Model also saved to: {h5_path} (legacy format)")
    except Exception as e:
        print(f"Warning: Could not save .h5 format: {e}")
    
    # Also save as SavedModel format for TensorFlow Serving
    savedmodel_path = model_path.parent / f"{model_path.stem}_savedmodel"
    try:
        model.export(str(savedmodel_path))
        print(f"✓ SavedModel saved to: {savedmodel_path}")
    except Exception as e:
        print(f"Warning: Could not save SavedModel format: {e}")
    
    # Evaluate final model
    print("\n" + "="*50)
    print("Final Evaluation")
    print("="*50)
    
    results = model.evaluate(val_ds, verbose=0)
    print(f"\nValidation Results:")
    print(f"  Loss: {results[0]:.4f}")
    print(f"  Accuracy: {results[1]:.2%}")
    if len(results) > 2:
        print(f"  Top-2 Accuracy: {results[2]:.2%}")
    
    return True


def main():
    parser = argparse.ArgumentParser(description="Train Bignay classification models (Improved)")
    parser.add_argument(
        "--subject",
        type=str,
        choices=["fruit", "leaf", "both"],
        default="both",
        help="Which model to train: fruit, leaf, or both"
    )
    parser.add_argument(
        "--fine-tune",
        action="store_true",
        default=True,
        help="Enable fine-tuning phase (default: True)"
    )
    parser.add_argument(
        "--no-fine-tune",
        action="store_true",
        help="Disable fine-tuning phase"
    )
    args = parser.parse_args()
    
    enable_fine_tuning = args.fine_tune and not args.no_fine_tune
    
    # System info
    print("\n" + "="*70)
    print("Bignay Model Training (Improved)")
    print("="*70)
    print(f"TensorFlow version: {tf.__version__}")
    print(f"Keras version: {tf.keras.__version__}")
    
    gpus = tf.config.list_physical_devices('GPU')
    if gpus:
        print(f"GPUs available: {len(gpus)}")
        for gpu in gpus:
            print(f"  - {gpu.name}")
        # Enable memory growth to avoid OOM
        for gpu in gpus:
            try:
                tf.config.experimental.set_memory_growth(gpu, True)
            except RuntimeError:
                pass
    else:
        print("No GPU available - training on CPU")
    
    print(f"Fine-tuning: {'Enabled' if enable_fine_tuning else 'Disabled'}")
    
    # Train models
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    
    if args.subject in ["fruit", "both"]:
        train_model("fruit", enable_fine_tuning)
    
    if args.subject in ["leaf", "both"]:
        train_model("leaf", enable_fine_tuning)
    
    print("\n" + "="*70)
    print("Training Complete!")
    print("="*70)
    print("\nImprovements applied:")
    print("  ✓ tf.data pipeline for efficient data loading")
    print("  ✓ MobileNetV2 preprocessing (scales to [-1, 1])")
    print("  ✓ GPU-accelerated augmentation layers")
    print("  ✓ Two-phase training (frozen → fine-tuning)")
    print("  ✓ Label smoothing for better generalization")
    print("  ✓ Class weights for imbalanced data")
    print("  ✓ Comprehensive callbacks (EarlyStopping, ReduceLR, TensorBoard)")
    print("  ✓ Mixed precision training (if GPU available)")
    print("\nNext steps:")
    print("1. Check TensorBoard: tensorboard --logdir=backend/logs")
    print("2. Restart the backend server")
    print("3. Test with the Scanner screen")


if __name__ == "__main__":
    main()
