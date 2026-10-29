"""Apresentação (Tkinter): janela principal, palco do avatar, painel da agenda e gravador de voz.

Regra da camada: só a thread principal toca no Tk. Tudo o que vem de outras threads chega
pelo barramento de eventos e é despachado a cada quadro."""
