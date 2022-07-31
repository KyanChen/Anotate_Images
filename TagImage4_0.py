import cv2
from osgeo import gdal
import os
import numpy as np
import glob
from skimage import io
import copy

# 争对单个文件夹
# Z取消一个标注
# D、A分别对应下一张图像和上一张图像
# F1, F2, ... 切换标注类别
# C 切换原图或者增强后的图像

IMG_PATH_DIR = r"J:\GF1_6已标\Positive_Patches\待确认\GF1_WFV1_E110.0_N17.9_20200703_L2A0004902374"
CLASSES = ['0', '1', '3']
IMG_FORMAT = 'tiff'
MODE = 'normal'

SCALARS = [(255, 0, 0), (0, 0, 255), (0, 255, 0), (200, 5, 200)]
# SCALARS = [(x, x, x) for x in range(0, 255, 2)]


class AnnotateImage:

    def __init__(self, path_dir, mode='gdal'):
        self.path_dir = path_dir
        self.file_list = self.get_file_list(self.path_dir)
        assert len(self.file_list), path_dir + ' No Data!'
        self.dep_file = path_dir + '/temp'
        os.makedirs(self.dep_file, exist_ok=True)
        self.mode = mode
        self.cur_file_id = self.read_resume_file_id(self.dep_file)
        self.cur_file_id = np.clip(self.cur_file_id, a_min=0, a_max=len(self.file_list)-1)
        self.labels = np.array([])
        self.flag_is_draw_finished = True
        self.temp_draw_box = [0, 0, 0, 0]
        self.cur_XY = [0, 0]
        self.isDrawFinished = True
        self.size_infos = None
        self.cur_annotate_label = 0

    @staticmethod
    def get_file_list(path):
        file_list = glob.glob(path + '/*.%s' % IMG_FORMAT)
        file_list.sort()
        return file_list

    @staticmethod
    def read_resume_file_id(path):
        path += '/resume_file_id.txt'
        if os.path.exists(path):
            with open(path, 'r') as file:
                return int(file.readline())
        else:
            return 0

    def write_resume_file_id(self, resume_file_id):
        path = self.dep_file + '/resume_file_id.txt'
        with open(path, 'w') as file:
            file.write(repr(resume_file_id))

    def read_annotations(self, img_file):
        def func(x):
            x = bytes.decode(x)
            return CLASSES.index(x)
        txt_file = img_file.replace(IMG_FORMAT, 'txt')
        if not os.path.exists(txt_file):
            with open(txt_file, 'w', encoding='utf-8') as f_read:
                pass
        if os.path.getsize(txt_file):
            self.labels = np.loadtxt(txt_file, dtype=float, ndmin=2, converters={0: func})

    def save_annotations(self, img_file):
        txt_file = img_file.replace(IMG_FORMAT, 'txt')
        if len(self.labels):
            labels = self.labels.astype(str)
            labels[:, 0:1] = np.array([CLASSES[x] for x in self.labels[:, 0].astype(np.int)]).reshape((-1, 1))
            np.savetxt(txt_file, labels, fmt=' %s %s %s %s %s', newline='\n')
        else:
            f = open(txt_file, 'w')
            f.close()
        self.labels = np.array([])

    # 创建回调函数
    def draw_rectangle(self, event, x, y, flags, param):
        self.cur_XY = [x, y]
        if event == cv2.EVENT_LBUTTONDOWN:
            self.flag_is_draw_finished = False
            self.temp_draw_box[0:2] = [x, y]
            self.temp_draw_box[2:] = [x, y]
        # 当鼠标左键按下并移动是绘制图形。event可以查看移动，flag查看是否按下
        elif event == cv2.EVENT_MOUSEMOVE and flags == cv2.EVENT_FLAG_LBUTTON:
            # self.flag_is_draw_finished = False
            self.temp_draw_box[2:] = [x, y]
        elif event == cv2.EVENT_LBUTTONUP:
            self.flag_is_draw_finished = True
            self.temp_draw_box[2:] = [x, y]
            left, top, right, bottom = self.refine_corners(*self.temp_draw_box)
            width_zoom = self.size_infos['present_width'] / self.size_infos['origin_width']
            height_zoom = self.size_infos['present_height'] / self.size_infos['origin_height']
            left, right = left / width_zoom, right / width_zoom
            top, bottom = top / height_zoom, bottom / height_zoom
            if len(self.labels):
                self.labels = np.vstack(
                    (self.labels, np.array([[self.cur_annotate_label, left, top, right, bottom]])))
            else:
                self.labels = np.array([[self.cur_annotate_label, left, top, right, bottom]])

    def refine_corners(self, x_1, y_1, x_2, y_2):
        if x_1 <= x_2:
            if y_1 <= y_2:
                left, top, right, bottom = x_1, y_1, x_2, y_2
            elif y_1 > y_2:
                left, top, right, bottom = x_1, y_2, x_2, y_1
        elif x_1 > x_2:
            if y_1 < y_2:
                left, top, right, bottom = x_2, y_1, x_1, y_2
            elif y_1 > y_2:
                left, top, right, bottom = x_2, y_2, x_1, y_1
        return left, top, right, bottom

    def read_img(self, file, mode):
        if mode == 'normal':
            ori_img = io.imread(file)
            if len(ori_img.shape) == 2:
                ori_img = cv2.cvtColor(ori_img, cv2.COLOR_GRAY2BGR)
            origin_height, origin_width, _ = ori_img.shape

            # 直方图均衡
            (b, g, r) = cv2.split(ori_img)
            bH = cv2.equalizeHist(b)
            gH = cv2.equalizeHist(g)
            rH = cv2.equalizeHist(r)
            img = cv2.merge((bH, gH, rH))

        elif mode == 'gdal':
            data_set = gdal.Open(file)
            origin_width = data_set.RasterXSize
            origin_height = data_set.RasterYSize
            origin_count = data_set.RasterCount
            present_width, present_height = int(origin_width * WIDTH_ZOOM), int(origin_height * HEIGHT_ZOOM)
            # m = data_set.ReadAsArray(0, 0, origin_width, origin_height)
            img_data = np.zeros((origin_count, present_height, present_width), dtype=np.uint16)
            data_set.ReadAsArray(0, 0, origin_width, origin_height,
                                 img_data, present_width, present_height,
                                 buf_type=gdal.GDT_UInt16, resample_alg=gdal.GRIORA_Bilinear)
            img_data = img_data[:3][::-1]
            img_data = np.transpose(img_data, (1, 2, 0))
            min_value, max_value = np.min(img_data), np.max(img_data)
            # 截断部分值
            min_value = 0 + 0.01 * min_value
            max_value = max_value - (max_value - min_value) * 0.01
            img_data = (img_data.astype(np.float32) - min_value) / (max_value - min_value + 1e-10)
            img = (np.clip(img_data, a_min=0, a_max=1) * 255).astype(np.uint8)
        self.size_infos = {'origin_width': origin_width, 'origin_height': origin_height}
        return ori_img, img

    def run(self):
        cv2.namedWindow('Annotation_Window', cv2.WINDOW_NORMAL)
        while self.cur_file_id < len(self.file_list):
            ori_img, img_equ = self.read_img(self.file_list[self.cur_file_id], mode=self.mode)
            self.read_annotations(self.file_list[self.cur_file_id])
            cv2.imshow("Annotation_Window", img_equ)
            cv2.waitKey(1)
            # 绑定事件
            cv2.setMouseCallback('Annotation_Window', self.draw_rectangle)
            flag_is_ori_img = False
            while True:
                win_rect = cv2.getWindowImageRect('Annotation_Window')
                self.size_infos['present_width'] = win_rect[2]
                self.size_infos['present_height'] = win_rect[3]
                if flag_is_ori_img:
                    img = ori_img.copy()
                else:
                    img = img_equ.copy()
                img = cv2.resize(img, (self.size_infos['present_width'], self.size_infos['present_height']), cv2.INTER_LINEAR)
                print(str(self.cur_file_id) + '/' + str(len(self.file_list)))
                tmp_bbox = self.labels.copy()
                for bbox in tmp_bbox:
                    width_zoom = self.size_infos['present_width'] / self.size_infos['origin_width']
                    height_zoom = self.size_infos['present_height'] / self.size_infos['origin_height']
                    bbox[1::2] *= width_zoom
                    bbox[2::2] *= height_zoom
                    class_id, left, top, right, bottom = bbox.astype(np.int)
                    cv2.rectangle(img, (left, top), (right, bottom), SCALARS[class_id], 2)
                    cv2.putText(img, CLASSES[class_id], (left, top), cv2.FONT_HERSHEY_COMPLEX, 0.8, SCALARS[class_id], 1)
                if not self.flag_is_draw_finished:
                    cv2.rectangle(img, tuple(self.temp_draw_box[:2]), tuple(self.temp_draw_box[2:]), (255, 255, 255), thickness=1)

                cv2.line(img, (self.cur_XY[0], 0), (self.cur_XY[0], self.size_infos['present_height']), (255, 255, 255), 1)
                cv2.line(img, (0, self.cur_XY[1]), (self.size_infos['present_width'], self.cur_XY[1]), (255, 255, 255), 1)
                cv2.putText(img, f"{self.cur_file_id}/{len(self.file_list)}:{CLASSES[self.cur_annotate_label]}",
                            (20, 30), cv2.FONT_HERSHEY_COMPLEX, 0.8, (255, 255, 255), 1)

                cv2.imshow("Annotation_Window", img)
                key_pressed = cv2.waitKeyEx(1)
                a_pressed = [ord('a'), ord('A')]
                d_pressed = [ord('d'), ord('D')]
                undo_pressed = [ord('z'), ord('Z')]
                change_pressed = [ord('c'), ord('C')]
                esc_pressed = [27]
                if key_pressed in d_pressed:
                    self.save_annotations(self.file_list[self.cur_file_id])
                    self.cur_file_id += 1
                    self.write_resume_file_id(self.cur_file_id)
                    break
                elif key_pressed in a_pressed:
                    self.save_annotations(self.file_list[self.cur_file_id])
                    self.cur_file_id -= 1
                    self.cur_file_id = np.maximum(0, self.cur_file_id)
                    self.write_resume_file_id(self.cur_file_id)
                    break
                elif key_pressed in undo_pressed:
                    if len(self.labels):
                        self.labels = self.labels[:-1, :]
                    else:
                        continue
                elif key_pressed in esc_pressed or cv2.getWindowProperty('Annotation_Window', 0) == -1:
                    self.save_annotations(self.file_list[self.cur_file_id])
                    self.write_resume_file_id(self.cur_file_id)
                    cv2.destroyAllWindows()
                    exit()
                elif key_pressed in change_pressed:
                    flag_is_ori_img = ~ flag_is_ori_img
                else:
                    if key_pressed != -1:
                        print(key_pressed)
                    if key_pressed in [7340032, 7405568, 7471104, 7536640]:
                        self.cur_annotate_label = [7340032, 7405568, 7471104, 7536640].index(key_pressed)


def main():
    annotator = AnnotateImage(IMG_PATH_DIR, MODE)
    annotator.run()


if __name__ == '__main__':
    main()


