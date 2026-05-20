from openai import OpenAI
import streamlit as st

client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

models = client.models.list()

for model in models.data:
    print(model.id)
