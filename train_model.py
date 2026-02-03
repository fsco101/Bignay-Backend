"""
Bignay Classification Model Training Script
============================================
Trains TensorFlow/Keras models for fruit and leaf classification.

Usage:
    python train_model.py --subject fruit
    python train_model.py --subject leaf
    python train_model.py --subject both

Output:
    - backend/model/fruit_model.h5
    - backend/model/leaf_model.h5
"""

import argparse
import os
from pathlib import Path

import numpy as np
import tensorflow as tf
from tensorflow.keras import layers, models, callbacks
from tensorflow.keras.preprocessing.image import ImageDataGenerator

# Paths
SCRIPT_DIR = Path(__file__).parent.resolve()
DATASET_DIR = SCRIPT_DIR.parent / "dataset"
MODEL_DIR = SCRIPT_DIR / "model"

# Training config
IMG_SIZE = 224
BATCH_SIZE = 16
EPOCHS = 50
LEARNING_RATE = 0.0001

# Class definitions (must match backend/app.py)
FRUIT_CLASSES = ["good", "mold", "overripe", "ripe", "unripe"]
LEAF_CLASSES = ["healthy", "mold"]


def create_model(num_classes: int, input_shape=(IMG_SIZE, IMG_SIZE, 3)) -> models.Model:
    """
    Creates a CNN model using transfer learning with MobileNetV2.
    MobileNetV2 is lightweight and works well with smaller datasets.
    """
    # Use MobileNetV2 as base (pretrained on ImageNet)
    base_model = tf.keras.applications.MobileNetV2(
        input_shape=input_shape,
        include_top=False,
        weights="imagenet"
    )
    
    # Freeze base model layers initially
    base_model.trainable = False
    
    # Build the model
    model = models.Sequential([
        base_model,
        layers.GlobalAveragePooling2D(),
        layers.Dropout(0.3),
        layers.Dense(128, activation="relu"),
        layers.Dropout(0.2),
        layers.Dense(num_classes, activation="softmax")
    ])
    
    return model


def create_simple_cnn(num_classes: int, input_shape=(IMG_SIZE, IMG_SIZE, 3)) -> models.Model:
    """
    Creates a simple CNN for very small datasets (like leaf with only 17 images).
    Simpler architecture to avoid overfitting.
    """
    model = models.Sequential([
        layers.Conv2D(32, (3, 3), activation='relu', input_shape=input_shape),
        layers.MaxPooling2D((2, 2)),
        layers.Conv2D(64, (3, 3), activation='relu'),
        layers.MaxPooling2D((2, 2)),
        layers.Conv2D(64, (3, 3), activation='relu'),
        layers.MaxPooling2D((2, 2)),
        layers.Flatten(),
        layers.Dropout(0.5),
        layers.Dense(64, activation='relu'),
        layers.Dense(num_classes, activation='softmax')
    ])
    
    return model


def get_data_generators(data_dir: Path, classes: list[str], validation_split: float = 0.2):
    """
    Creates training and validation data generators with augmentation.
    Heavy augmentation helps with small/imbalanced datasets.
    """
    # Training data generator with augmentation
    train_datagen = ImageDataGenerator(
        rescale=1.0 / 255,
        rotation_range=40,
        width_shift_range=0.2,
        height_shift_range=0.2,
        shear_range=0.2,
        zoom_range=0.3,
        horizontal_flip=True,
        vertical_flip=True,
        brightness_range=[0.7, 1.3],
        fill_mode="nearest",
        validation_split=validation_split
    )
    
    # Validation data generator (no augmentation, just rescale)
    val_datagen = ImageDataGenerator(
        rescale=1.0 / 255,
        validation_split=validation_split
    )
    
    train_generator = train_datagen.flow_from_directory(
        data_dir,
        target_size=(IMG_SIZE, IMG_SIZE),
        batch_size=BATCH_SIZE,
        class_mode="categorical",
        classes=classes,
        subset="training",
        shuffle=True
    )
    
    val_generator = val_datagen.flow_from_directory(
        data_dir,
        target_size=(IMG_SIZE, IMG_SIZE),
        batch_size=BATCH_SIZE,
        class_mode="categorical",
        classes=classes,
        subset="validation",
        shuffle=False
    )
    
    return train_generator, val_generator


def compute_class_weights(train_generator) -> dict:
    """
    Computes class weights to handle imbalanced datasets.
    Classes with fewer samples get higher weights.
    """
    from sklearn.utils.class_weight import compute_class_weight
    
    class_weights = compute_class_weight(
        class_weight="balanced",
        classes=np.unique(train_generator.classes),
        y=train_generator.classes
    )
    
    return dict(enumerate(class_weights))


def train_model(subject: str):
    """
    Trains a classification model for the specified subject (fruit or leaf).
    """
    print(f"\n{'='*60}")
    print(f"Training {subject.upper()} classification model")
    print(f"{'='*60}\n")
    
    # Setup paths and classes
    if subject == "fruit":
        data_dir = DATASET_DIR / "fruit"
        classes = FRUIT_CLASSES
        model_path = MODEL_DIR / "fruit_model.h5"
    else:
        data_dir = DATASET_DIR / "leaf"
        classes = LEAF_CLASSES
        model_path = MODEL_DIR / "leaf_model.h5"
    
    # Check if data exists
    if not data_dir.exists():
        print(f"ERROR: Dataset directory not found: {data_dir}")
        return False
    
    # Count images per class
    print("Dataset summary:")
    total_images = 0
    for cls in classes:
        cls_dir = data_dir / cls
        if cls_dir.exists():
            count = len(list(cls_dir.glob("*")))
            total_images += count
            print(f"  {cls}: {count} images")
        else:
            print(f"  {cls}: 0 images (folder missing)")
    print(f"  Total: {total_images} images\n")
    
    if total_images < 10:
        print(f"ERROR: Not enough images to train. Need at least 10, found {total_images}")
        return False
    
    # Create data generators
    print("Loading and augmenting data...")
    train_gen, val_gen = get_data_generators(data_dir, classes)
    
    print(f"Training samples: {train_gen.samples}")
    print(f"Validation samples: {val_gen.samples}")
    print(f"Classes: {train_gen.class_indices}\n")
    
    # Compute class weights for imbalanced data
    try:
        class_weights = compute_class_weights(train_gen)
        print(f"Class weights (for imbalanced data): {class_weights}\n")
    except Exception as e:
        print(f"Warning: Could not compute class weights: {e}")
        class_weights = None
    
    # Create model
    print("Building model...")
    num_classes = len(classes)
    
    # Use simpler model for very small datasets
    if total_images < 50:
        print("Using simple CNN (small dataset detected)")
        model = create_simple_cnn(num_classes)
    else:
        print("Using MobileNetV2 transfer learning")
        model = create_model(num_classes)
    
    # Compile model
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=LEARNING_RATE),
        loss="categorical_crossentropy",
        metrics=["accuracy"]
    )
    
    model.summary()
    
    # Setup callbacks
    model_callbacks = [
        callbacks.EarlyStopping(
            monitor="val_loss",
            patience=10,
            restore_best_weights=True,
            verbose=1
        ),
        callbacks.ReduceLROnPlateau(
            monitor="val_loss",
            factor=0.5,
            patience=5,
            min_lr=1e-7,
            verbose=1
        ),
        callbacks.ModelCheckpoint(
            str(model_path),
            monitor="val_accuracy",
            save_best_only=True,
            verbose=1
        )
    ]
    
    # Train
    print("\nStarting training...\n")
    
    steps_per_epoch = max(1, train_gen.samples // BATCH_SIZE)
    validation_steps = max(1, val_gen.samples // BATCH_SIZE)
    
    history = model.fit(
        train_gen,
        steps_per_epoch=steps_per_epoch,
        epochs=EPOCHS,
        validation_data=val_gen,
        validation_steps=validation_steps,
        class_weight=class_weights,
        callbacks=model_callbacks,
        verbose=1
    )
    
    # Save final model
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model.save(str(model_path))
    print(f"\n✓ Model saved to: {model_path}")
    
    # Print final metrics
    final_acc = history.history["accuracy"][-1]
    final_val_acc = history.history["val_accuracy"][-1]
    best_val_acc = max(history.history["val_accuracy"])
    
    print(f"\nTraining Results:")
    print(f"  Final training accuracy: {final_acc:.2%}")
    print(f"  Final validation accuracy: {final_val_acc:.2%}")
    print(f"  Best validation accuracy: {best_val_acc:.2%}")
    
    return True


def main():
    parser = argparse.ArgumentParser(description="Train Bignay classification models")
    parser.add_argument(
        "--subject",
        type=str,
        choices=["fruit", "leaf", "both"],
        default="both",
        help="Which model to train: fruit, leaf, or both (default: both)"
    )
    args = parser.parse_args()
    
    # Check TensorFlow
    print(f"TensorFlow version: {tf.__version__}")
    print(f"GPU available: {len(tf.config.list_physical_devices('GPU')) > 0}")
    
    # Ensure model directory exists
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    
    if args.subject in ["fruit", "both"]:
        train_model("fruit")
    
    if args.subject in ["leaf", "both"]:
        train_model("leaf")
    
    print("\n" + "="*60)
    print("Training complete!")
    print("="*60)
    print("\nNext steps:")
    print("1. Restart the backend server")
    print("2. The models will be automatically loaded")
    print("3. Test with the /predict endpoint or Scanner screen")


if __name__ == "__main__":
    main()
