# -*- coding: utf-8 -*-
"""T5_Model_For_Text2price_Task.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1BugUTBZnMqebxUtCmZ01JVLw_Al7gOmh
"""

from google.colab import drive
drive.mount('/content/drive')

!pip install --quiet transformers
!pip install --quiet sentencepiece

import numpy as np
import pandas as pd
import torch
from sklearn.model_selection import train_test_split
import os
import pickle
import torch.nn as nn
from torch.optim import AdamW
from transformers import AdamW, get_linear_schedule_with_warmup
from transformers import T5Model, T5Config
from transformers import get_linear_schedule_with_warmup
from sklearn.preprocessing import StandardScaler
from torch.utils.data import TensorDataset, DataLoader
from torch.nn.utils import clip_grad_norm_
from sklearn.metrics import mean_squared_error, mean_absolute_error
from transformers import T5Tokenizer, T5Model, T5Config
from google.colab import drive

drive.mount('/content/drive')
cwd = "/content/drive/MyDrive/deep/"
os.chdir(cwd)

# Load and preprocess data
file_path = "/content/drive/MyDrive/deep/traing_test.csv"
#file_path = "/content/drive/MyDrive/deep/price_text.csv"
data = pd.read_csv(file_path)
sample_size = 1000
sample_df = data.sample(n=sample_size, random_state=42)
train_data, test_data = train_test_split(sample_df, train_size=0.8, random_state=42)

#df = train_data
df = train_data[['ID', 'price', 'text']]
# Tokenization and data preparation
tokenizer = T5Tokenizer.from_pretrained('t5-base')

encoded_corpus = tokenizer.batch_encode_plus(
    df.text.tolist(),
    padding='longest',
    truncation=True,
    return_attention_mask=True,
    return_tensors='pt'
)

input_ids = encoded_corpus['input_ids'].to(torch.long)
attention_mask = encoded_corpus['attention_mask'].to(torch.float)

def split_long_sequences(input_ids, attention_mask):
    input_ids_list = []
    attention_mask_list = []

    for i in range(len(input_ids)):
        input_ids_list.append(input_ids[i])
        attention_mask_list.append(attention_mask[i])

    return input_ids_list, attention_mask_list

input_ids, attention_mask = split_long_sequences(input_ids, attention_mask)
labels = df.price.to_numpy()

# Convert to tensors
input_ids = [torch.LongTensor(ids) for ids in input_ids]
input_ids = torch.stack(input_ids)
attention_mask = torch.stack([mask.clone().detach() for mask in attention_mask])
labels = torch.tensor(labels).view(-1, 1)

# Train-test split
max_sequence_length = 512
test_size = 0.1
seed = 42

train_inputs, test_inputs, train_labels, test_labels = \
    train_test_split(input_ids, labels, test_size=test_size, random_state=seed)

train_masks, test_masks, _, _ = \
    train_test_split(attention_mask, labels, test_size=test_size, random_state=seed)

# Padding for training set
train_inputs = np.array([np.pad(seq, (0, max_sequence_length - len(seq)), mode='constant') for seq in train_inputs])
train_masks = np.array([np.pad(seq, (0, max_sequence_length - len(seq)), mode='constant') for seq in train_masks])

# Padding for the test set
test_inputs = np.array([np.pad(seq, (0, max_sequence_length - len(seq)), mode='constant') for seq in test_inputs])
test_masks = np.array([np.pad(seq, (0, max_sequence_length - len(seq)), mode='constant') for seq in test_masks])

# Standardize labels
price_scaler = StandardScaler()
price_scaler.fit(train_labels.reshape(-1, 1))
train_labels = price_scaler.transform(train_labels.reshape(-1, 1))
test_labels = price_scaler.transform(test_labels.reshape(-1, 1))

# Batch size
batch_size = 4

def create_dataloaders(inputs, masks, labels, batch_size):
    input_tensor = torch.tensor(inputs).to(torch.float32)
    mask_tensor = torch.tensor(masks).to(torch.float32)
    labels_tensor = torch.tensor(labels).to(torch.float32)
    dataset = TensorDataset(input_tensor, mask_tensor, labels_tensor)
    dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=True)
    return dataloader

# Create dataloaders
train_dataloader = create_dataloaders(train_inputs, train_masks, train_labels, batch_size)
test_dataloader = create_dataloaders(test_inputs, test_masks, test_labels, batch_size)

# Model definition  تعريف النموذج
class T5Regressor(nn.Module):
    def __init__(self, drop_rate=0.2, freeze_t5=False):
        super(T5Regressor, self).__init__()
        D_in, D_out = 768, 1

        t5_config = T5Config.from_pretrained('t5-base')
        self.t5 = T5Model.from_pretrained('t5-base', config=t5_config)
        if freeze_t5:
            for param in self.t5.parameters():
                param.requires_grad = False

        self.regressor = nn.Sequential(
            nn.Dropout(drop_rate),
            nn.Linear(D_in, D_out)
        )

    def forward(self, input_ids, attention_mask):
        outputs = self.t5.encoder(input_ids=input_ids, attention_mask=attention_mask, return_dict=True)
        last_hidden_state = outputs.last_hidden_state[:, 0, :]
        logits = self.regressor(last_hidden_state).squeeze(1)
        return logits

# Custom criterion for accuracy  # معيار مخصص للدقة
def custom_criterion(logits, labels, scaler):
    # Convert predictions to original scale
    predicted_prices = scaler.inverse_transform(logits.detach().cpu().numpy().reshape(-1, 1))
    labels_original = scaler.inverse_transform(labels.cpu().numpy().reshape(-1, 1))

    # Compute accuracy (you can customize this based on your specific metric)
    accuracy = custom_accuracy_function(predicted_prices, labels_original)

    return accuracy

def custom_accuracy_function(predictions, labels):
    # Implement your custom accuracy function here
    # For example, you can use mean absolute percentage error (MAPE)
    abs_percentage_error = np.abs((predictions - labels) / labels)
    accuracy = 100.0 - np.mean(abs_percentage_error) * 100.0
    return np.clip(accuracy, 0.0, 100.0)

# Initialize model, optimizer, and scheduler
model = T5Regressor(drop_rate=0.2)
if torch.cuda.is_available():
    device = torch.device("cuda")
    print("Using GPU.")
else:
    print("No GPU available, using the CPU instead.")
    device = torch.device("cpu")

model.to(device)

# Assuming your model is already defined as 'model'
optimizer = AdamW(model.parameters(), lr=5e-5, eps=1e-8)
epochs = 5
total_steps = len(train_dataloader) * epochs

# Learning rate scheduling with warm-up
scheduler = get_linear_schedule_with_warmup(optimizer, num_warmup_steps=int(0.1 * total_steps), num_training_steps=total_steps)

# Loss function (you can choose between L1Loss and MSELoss)
loss_function = nn.L1Loss()
# loss_function = nn.MSELoss()

# Training loop with evaluation on the test set
for epoch in range(epochs):
    print(f"Epoch {epoch + 1}/{epochs}")
    model.train()
    total_train_accuracy = 0.0  # Accumulator for training accuracy across batches

    for step, batch in enumerate(train_dataloader):
        batch_inputs, batch_masks, batch_labels = tuple(b.to(device) for b in batch)
        batch_inputs = batch_inputs.to(torch.long)
        optimizer.zero_grad()
        logits = model(batch_inputs, batch_masks)
        loss = loss_function(logits, batch_labels.squeeze())

        # Calculate custom accuracy
        accuracy = custom_criterion(logits, batch_labels, price_scaler)
        total_train_accuracy += accuracy  # Accumulate accuracy across batches

        loss.backward()
        clip_grad_norm_(model.parameters(), 2)
        optimizer.step()
        scheduler.step()

    # Calculate average training accuracy for the epoch
    average_train_accuracy = total_train_accuracy / len(train_dataloader)
    #print(f"Training Accuracy: {average_train_accuracy}%")

    # Evaluate on the test set after each epoch
    model.eval()
    total_mse = 0.0
    total_mae = 0.0
    total_samples = 0
    total_accuracy = 0.0

    with torch.no_grad():
        for batch in test_dataloader:
            batch_inputs, batch_masks, batch_labels = tuple(b.to(device) for b in batch)
            batch_inputs = batch_inputs.to(torch.long)
            logits = model(batch_inputs, batch_masks)

            # Calculate custom accuracy
            accuracy = custom_criterion(logits, batch_labels, price_scaler)
            print(f" Accuracy: {accuracy}%")

            # Convert predictions to original scale
            predicted_prices = price_scaler.inverse_transform(logits.detach().cpu().numpy().reshape(-1, 1))
            batch_labels_original = price_scaler.inverse_transform(batch_labels.cpu().numpy().reshape(-1, 1))

            # Compute metrics
            mse = mean_squared_error(batch_labels_original, predicted_prices)
            mae = mean_absolute_error(batch_labels_original, predicted_prices)

            total_mse += mse * len(batch_labels)
            total_mae += mae * len(batch_labels)
            total_samples += len(batch_labels)
            total_accuracy += accuracy * len(batch_labels)

    average_mse = total_mse / total_samples
    average_mae = total_mae / total_samples
    average_accuracy = total_accuracy / total_samples

    print(f" MSE: {average_mse},  MAE: {average_mae},  Accuracy: {average_accuracy}%")

# Save the model after training
model_save_path = '/content/drive/MyDrive/deep/final/text2price.pth'
tokenizer_save_path = '/content/drive/MyDrive/deep/final/text2price_tokenizer'
scaler_path = '/content/drive/MyDrive/deep/final/scaler.pkl'  # Path to save the scaler file
# Save the scaler after training
with open(scaler_path, 'wb') as scaler_file:
    pickle.dump(price_scaler, scaler_file)

def save_model_to_drive(model, tokenizer, model_save_path, tokenizer_save_path):
    torch.save(model.state_dict(), model_save_path)
    tokenizer.save_pretrained(tokenizer_save_path)
    print("Model and tokenizer saved to Google Drive.")

# Example usage:
save_model_to_drive(model, tokenizer, model_save_path, tokenizer_save_path)

def load_model_from_drive(model, tokenizer, model_save_path, tokenizer_save_path):
    model.load_state_dict(torch.load(model_save_path))
    tokenizer = T5Tokenizer.from_pretrained(tokenizer_save_path)
    print("Model and tokenizer loaded from Google Drive.")
    return model, tokenizer

# Example usage:
loaded_model, loaded_tokenizer = load_model_from_drive(model, tokenizer, model_save_path, tokenizer_save_path)


def predict_price(model, tokenizer, text, scaler, device):
    # Tokenize the input text
    encoded_text = tokenizer.encode_plus(
        text,
        padding='longest',
        truncation=True,
        return_attention_mask=True,
        return_tensors='pt'
    )

    # Move the input tensors to the same device as the model
    input_ids = encoded_text['input_ids'].to(device)
    attention_mask = encoded_text['attention_mask'].to(device)

    # Make predictions using the trained model
    with torch.no_grad():
        logits = model(input_ids, attention_mask)

    # Move logits to CPU
    logits = logits.cpu()

    # Convert logits to predicted price
    predicted_price = scaler.inverse_transform(logits.numpy().reshape(-1, 1))

    return predicted_price[0, 0]

# Example text to predict price
example_text = "jbl boombox 2 portabl bluetooth speaker power sound monstrou bass ipx7 waterproof 24 hour playtim powerbank jbl partyboost speaker pair home outdoor black bl boombox 2 portabl bluetooth speaker bring monstrou bass bold design incred 24 hour play time ipx7 fulli waterproof portabl power speaker pump massiv sound day night with jbl partyboost connect jbl partyboost compat speaker turn parti jbl boombox 2 keep friend danc built powerbank keep devic charg so groov dusk till dawn keep go strong power jbl origin pro sound and monstrou bass get loudest massiv jbl origin pro sound power portabl jbl boombox 2 speaker it pump power deep bass like club power jbl portabl design the icon grip handl make easi transport jbl boombox 2 portabl speaker 24 hour of playtim the fun stop pack incred 24 hour batteri life jbl boombox 2 let parti day night wireless bluetooth stream wirelessli stream music phone tablet bluetooth enabl devic ipx7 waterproof bring speaker anywher pool parti perfect sudden rainstorm cover bash beach jbl boombox 2 ipx7 waterproof fearless outdoor entertain"

# Now you can use this scaler in your predict_price function
predicted_price = predict_price(loaded_model, loaded_tokenizer, example_text, price_scaler, device)

# Print the predicted price
print(f"Predicted Price: {predicted_price}")

!pip install --quiet transformers
!pip install --quiet sentencepiece
# Mount Google Drive
from google.colab import drive
drive.mount('/content/drive')

import torch
import torch.nn as nn
from transformers import T5Model, T5Config, T5Tokenizer
from torch.utils.data import TensorDataset, DataLoader
from torch.nn.utils import clip_grad_norm_
from sklearn.metrics import mean_squared_error, mean_absolute_error
from transformers import AdamW, get_linear_schedule_with_warmup
import numpy as np
import pickle

# Load tokenizer
tokenizer = T5Tokenizer.from_pretrained('t5-base')

# Define the model architecture
class T5Regressor(nn.Module):
    def __init__(self, drop_rate=0.2, freeze_t5=False):
        super(T5Regressor, self).__init__()
        D_in, D_out = 768, 1

        t5_config = T5Config.from_pretrained('t5-base')
        self.t5 = T5Model.from_pretrained('t5-base', config=t5_config)
        if freeze_t5:
            for param in self.t5.parameters():
                param.requires_grad = False

        self.regressor = nn.Sequential(
            nn.Dropout(drop_rate),
            nn.Linear(D_in, D_out)
        )

    def forward(self, input_ids, attention_mask):
        outputs = self.t5.encoder(input_ids=input_ids, attention_mask=attention_mask, return_dict=True)
        last_hidden_state = outputs.last_hidden_state[:, 0, :]
        logits = self.regressor(last_hidden_state).squeeze(1)
        return logits

# Load model weights
model = T5Regressor(drop_rate=0.2)
model_path = '/content/drive/MyDrive/deep/final/text2price.pth'
model.load_state_dict(torch.load(model_path, map_location=torch.device('cpu')))
model.eval()

# Load the scaler
scaler_path = '/content/drive/MyDrive/deep/final/scaler.pkl' # Replace with your scaler path

# Load the scaler
with open(scaler_path, 'rb') as scaler_file:
    price_scaler = pickle.load(scaler_file)

# Define the prediction function
def predict_price(model, tokenizer, text, scaler, device):
    # Tokenize the input text
    encoded_text = tokenizer.encode_plus(
        text,
        padding='longest',
        truncation=True,
        return_attention_mask=True,
        return_tensors='pt'
    )

    # Move the input tensors to the specified device
    input_ids = encoded_text['input_ids'].to(device)
    attention_mask = encoded_text['attention_mask'].to(device)

    # Move the model to the specified device
    model = model.to(device)

    # Make predictions using the trained model
    with torch.no_grad():
        logits = model(input_ids, attention_mask)

    # Move logits to CPU
    logits = logits.cpu()

    # Convert logits to predicted price
    predicted_price = scaler.inverse_transform(logits.numpy().reshape(-1, 1))

    return predicted_price[0, 0]

# Example text to predict price
example_text = "skullcandi crusher anc person nois cancel wireless headphon black skullcandi adjust sensori bass digit activ nois cancel person sound skullcandi app 24 hour batteri life rapid charg built tile tracker nan 4.5"
# Now you can use this scaler in your predict_price function
device = 'cuda' if torch.cuda.is_available() else 'cpu'
predicted_price = predict_price(model, tokenizer, example_text, price_scaler, device)

# Print the predicted price
print(f"Predicted Price: {predicted_price}")

!pip install --quiet gradio

!pip install --quiet typing_extensions

import gradio as gr

# Define the Gradio prediction function
def gradio_predict_price(text):
    # Use the previously defined predict_price function
    predicted_price = predict_price(model, tokenizer, text, price_scaler, device)
    return float(predicted_price)  # Convert the result to a float

# Create the Gradio interface
iface = gr.Interface(
    fn=gradio_predict_price,
    inputs="text",
    outputs="text",  # Use "text" as the output type
    live=True,
    title="Text-to-Price Prediction",
    description="Enter a product description, and the model will predict the price.",
)

# Launch the Gradio interface
iface.launch()