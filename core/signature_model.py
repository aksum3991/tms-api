# import torch
# import torch.nn as nn
# from torchvision import models, transforms
# from PIL import Image
# from scipy.spatial.distance import cosine

# # Define the Siamese Network
# class SiameseNetwork(nn.Module):
#     def __init__(self):
#         super(SiameseNetwork, self).__init__()
#         self.resnet = models.resnet18(pretrained=True)
#         self.resnet.fc = nn.Linear(self.resnet.fc.in_features, 256)

#     def forward(self, x):
#         return self.resnet(x)

# # Load model and set to eval mode (do this once, not per request)
# model = SiameseNetwork()
# model.eval()

# # Define image transformations
# transform = transforms.Compose([
#     transforms.Resize((224, 224)),
#     transforms.ToTensor(),
#     transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
# ])

# def get_image_embedding(image_path, model=model, transform=transform):
#     image = Image.open(image_path).convert("RGB")
#     image = transform(image).unsqueeze(0)  # Add batch dimension
#     with torch.no_grad():
#         features = model(image)
#     return features.squeeze().cpu().numpy()

# def compare_signatures_with_model(path1, path2, model=model, transform=transform):
#     embedding1 = get_image_embedding(path1, model, transform)
#     embedding2 = get_image_embedding(path2, model, transform)
#     similarity = 1 - cosine(embedding1, embedding2)
#     return similarity